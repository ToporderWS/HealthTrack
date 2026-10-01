# -*- coding: utf-8 -*-
"""数据导出服务（本批实现 **E-01 ~ E-04**）。

依据（**逐条落实，不发明字段**）：
- 《S1-B 第二批 API 接口设计文档》§十「数据导出 API（模块 E，4 个）」
- 《S1-A 安全规则冻结清单》§4（每次导出二次验密，无豁免）/ §8（有效期）
- 《S1-D 技术方案最终冻结》§5.3（导出任务 **同步生成**）/ §6.3（时间与隔离口径）

冻结口径：
- **二次验密**：每次导出必做，**无小范围豁免**；同一会话连错 ``VERIFY_MAX_EXPORT``(=3) 次
  → ``429 SESSION_VERIFY_ABORTED``（**不纳入登录锁定**，计数存 ``user_session.export_pwd_fail_count``）；
  验密**成功即清零**该计数。
- **生成方式**：S1-D §5.3 冻结为 **同步生成** —— 不引入 Celery / Redis / MQ / 后台 worker；
  生成完成后直接返回**真实最终状态**（成功即 ``ready``）。
- **进行中冲突**：已有 ``pending`` / ``ready`` 任务 → ``409 EXPORT_IN_PROGRESS``。
- **有效期**：``download_expires_at`` = 生成 + 10 分钟；``purge_at`` = 生成 + 60 分钟；
  ``expired`` / ``purged`` **按当前时间动态判定**（本批不实现后台清理任务）。
- **隔离**：列表 / 查询恒带 ``user_id``；下载为 ``id + user_id + file_token`` **三条件**。
- **不外泄**：响应**永不返回** ``file_path``；导出内容**不含软删数据**、
  **不含 ``user_id``**、**不含数据库内部主键 ``id``**、不含 Token / 密钥 / session 信息。
- **日志**：不记录健康数值 / 用户名 / ``user_id`` / 完整 ``file_path``。

边界说明（本批口径，**未新增字段**）：
- 导出文件列 = **R-02 / R-03 已冻结的记录事实字段**，剔除 ``id`` 与 ``user_id``：
  ``metric_type`` / ``value_1`` / ``value_2`` / ``value_3`` / ``unit`` /
  ``attr_1`` / ``attr_2`` / ``recorded_at`` / ``time_start`` / ``note`` / ``tags`` / ``created_at``。
- 数值归一与 R-02 一致：整数值输出 ``int``，否则 ``float``（保证导出格式稳定）。
- 时间统一 ``YYYY-MM-DD HH:mm:ss``（D-4 本地墙上时间，无时区后缀）。
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from flask import current_app
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode, FieldErrorCode, field_error
from app.core.paging import decode_cursor, encode_cursor, format_dt, parse_limit, parse_range_bound
from app.core.security import normalize_password, now_local, verify_password
from app.models.export_job import ExportJob
from app.models.health_record import HealthRecord
from app.models.record_tag import RecordTag
from app.services import metric_rules

logger = logging.getLogger(__name__)

#: 允许的导出格式（S1-B §十 E-01）
ALLOWED_FORMATS: Tuple[str, ...] = ("csv", "json")

#: 下载凭证随机字节数：16 字节 = 32 位十六进制（匹配 ``export_job.file_token CHAR(32)``）
FILE_TOKEN_BYTES = 16

#: 进行中状态（阻塞新导出）
IN_PROGRESS_STATUSES: Tuple[str, ...] = ("pending", "ready")

#: 可下载状态（窗口内）
DOWNLOADABLE_STATUSES: Tuple[str, ...] = ("ready", "downloaded")

#: 导出列（R-02 / R-03 事实字段；**不含 ``id`` / ``user_id`` / Token / 内部标识**）
EXPORT_COLUMNS: Tuple[str, ...] = (
    "metric_type", "value_1", "value_2", "value_3", "unit",
    "attr_1", "attr_2", "recorded_at", "time_start", "note", "tags", "created_at",
)

#: CSV 中子表（``tags``）的分隔符
TAG_SEPARATOR = "|"

#: 文件名前缀（服务端生成，**不含用户名 / user_id**）
EXPORT_FILENAME_PREFIX = "healthtrack_export"


# ════════════════════════════════════════════════════════════════════
# 基础工具
# ════════════════════════════════════════════════════════════════════
def _num(value: Optional[Decimal]) -> Optional[Any]:
    """数值输出：整数值输出 ``int``，否则 ``float``（与 R-02 口径一致，保证格式稳定）。"""
    if value is None:
        return None
    dec = Decimal(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _clean(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _ttl_minutes(cfg: Dict[str, Any]) -> int:
    return int(cfg.get("EXPORT_DOWNLOAD_TTL_MINUTES") or 10)


def _purge_minutes(cfg: Dict[str, Any]) -> int:
    return int(cfg.get("EXPORT_PURGE_MINUTES") or 60)


def effective_status(job: ExportJob, now: Optional[datetime] = None) -> str:
    """任务**有效状态**（``expired`` / ``purged`` 按当前时间动态判定）。

    判定顺序：``purge_at`` 已过 → ``purged``；``download_expires_at`` 已过 → ``expired``；
    否则回落到库内 ``status``。
    """
    now = now or now_local()
    status = str(job.status)
    if status == "purged":
        return "purged"
    if job.purge_at is not None and now >= job.purge_at:
        return "purged"
    if status == "expired":
        return "expired"
    if job.download_expires_at is not None and now >= job.download_expires_at:
        return "expired"
    return status


def job_view(job: ExportJob, now: Optional[datetime] = None,
             include_token: bool = False) -> Dict[str, Any]:
    """E-02 / E-04 的任务视图。

    - **永不包含** ``file_path``；
    - ``include_token=True`` 时携带 ``file_token`` 键，但**仅当任务当前可下载**
      （``ready`` / ``downloaded``）时给值，其余状态一律 ``null``（缩小凭证暴露面）；
    - ``include_token=False``（E-04 列表）时**完全不出现** ``file_token`` 键。
    """
    now = now or now_local()
    status = effective_status(job, now)
    data: Dict[str, Any] = {
        "export_id": int(job.id),
        "format": job.format,
        "status": status,
        "record_count": job.record_count,
        "file_size_bytes": job.file_size_bytes,
        "download_expires_at": format_dt(job.download_expires_at),
        "purge_at": format_dt(job.purge_at),
        "downloaded_at": format_dt(job.downloaded_at),
        "created_at": format_dt(job.created_at),
    }
    if include_token:
        data["file_token"] = job.file_token if status in DOWNLOADABLE_STATUSES else None
    return data


# ════════════════════════════════════════════════════════════════════
# E-01 参数解析（非法 → 400 INVALID_PARAM；缺参 → 400 携带字段级明细）
# ════════════════════════════════════════════════════════════════════
def _parse_format(raw: Any) -> str:
    text = _clean(raw)
    if text is None:
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error("format", FieldErrorCode.REQUIRED, "导出格式不能为空")
        ])
    value = text.lower()
    if value not in ALLOWED_FORMATS:
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error("format", FieldErrorCode.INVALID_FORMAT, "导出格式仅支持 csv / json")
        ])
    return value


def _parse_metric_types(raw: Any) -> Optional[Tuple[str, ...]]:
    """``null`` = 全部指标；数组则逐项校验（按 ``METRIC_TYPES`` 固定序归一）。"""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error("metric_types", FieldErrorCode.INVALID_TYPE, "指标范围应为数组")
        ])
    picked: List[str] = []
    for item in raw:
        text = _clean(item)
        if text is None or text not in metric_rules.METRIC_TYPES:
            raise ApiError(ErrorCode.INVALID_PARAM, errors=[
                field_error("metric_types", FieldErrorCode.INVALID_FORMAT, "指标类型不在允许范围内")
            ])
        if text not in picked:
            picked.append(text)
    if not picked:
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error("metric_types", FieldErrorCode.INVALID_FORMAT, "指标范围不能为空数组（全部指标请传 null）")
        ])
    ordered = tuple(t for t in metric_rules.METRIC_TYPES if t in set(picked))
    return ordered


def _parse_range(payload: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """半开区间 ``[range_start, range_end)``；``range_start >= range_end`` → 400。"""
    start = parse_range_bound("range_start", payload.get("range_start"))
    end = parse_range_bound("range_end", payload.get("range_end"))
    if start is not None and end is not None and start >= end:
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error("range_end", FieldErrorCode.INVALID_FORMAT, "结束时间须晚于开始时间")
        ])
    return start, end


# ════════════════════════════════════════════════════════════════════
# 取数（恒带 user_id + is_deleted = 0）
# ════════════════════════════════════════════════════════════════════
def _fetch_records(db: Session, user_id: int, metric_types: Optional[Sequence[str]],
                   start: Optional[datetime], end: Optional[datetime]) -> List[HealthRecord]:
    """导出取数：``user_id`` + ``is_deleted = 0`` + 半开区间；按发生时间升序。"""
    conditions = [HealthRecord.user_id == user_id, HealthRecord.is_deleted == 0]
    if metric_types:
        conditions.append(HealthRecord.metric_type.in_(list(metric_types)))
    if start is not None:
        conditions.append(HealthRecord.recorded_at >= start)
    if end is not None:
        conditions.append(HealthRecord.recorded_at < end)
    return list(db.execute(
        select(HealthRecord)
        .where(*conditions)
        .order_by(HealthRecord.recorded_at.asc(), HealthRecord.id.asc())
    ).scalars().all())


def _tags_of(db: Session, record_ids: Sequence[int], user_id: int) -> Dict[int, List[str]]:
    """批量取标签（**只取未软删行**）。"""
    if not record_ids:
        return {}
    rows = db.execute(
        select(RecordTag.record_id, RecordTag.tag_value)
        .where(
            RecordTag.user_id == user_id,
            RecordTag.record_id.in_(list(record_ids)),
            RecordTag.is_deleted == 0,
        )
        .order_by(RecordTag.record_id.asc(), RecordTag.id.asc())
    ).all()
    out: Dict[int, List[str]] = {}
    for record_id, tag in rows:
        out.setdefault(int(record_id), []).append(tag)
    return out


def _record_row(record: HealthRecord, tags: Sequence[str]) -> Dict[str, Any]:
    """导出一行（**不含 ``id`` / ``user_id``**）。"""
    return {
        "metric_type": record.metric_type,
        "value_1": _num(record.value_1),
        "value_2": _num(record.value_2),
        "value_3": _num(record.value_3),
        "unit": record.unit,
        "attr_1": record.attr_1,
        "attr_2": record.attr_2,
        "recorded_at": format_dt(record.recorded_at),
        "time_start": format_dt(record.time_start),
        "note": record.note,
        "tags": list(tags or []),
        "created_at": format_dt(record.created_at),
    }


def _rows(records: Sequence[HealthRecord], tags_map: Dict[int, List[str]]) -> List[Dict[str, Any]]:
    return [_record_row(r, tags_map.get(int(r.id), [])) for r in records]


# ════════════════════════════════════════════════════════════════════
# 渲染（csv / json）
# ════════════════════════════════════════════════════════════════════
def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return TAG_SEPARATOR.join(str(v) for v in value)
    return str(value)


def render_csv(rows: Sequence[Dict[str, Any]]) -> bytes:
    """CSV（UTF-8 无 BOM；表头 = ``EXPORT_COLUMNS``）。"""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(list(EXPORT_COLUMNS))
    for row in rows:
        writer.writerow([_csv_cell(row.get(col)) for col in EXPORT_COLUMNS])
    return buf.getvalue().encode("utf-8")


def render_json(rows: Sequence[Dict[str, Any]]) -> bytes:
    """JSON（UTF-8；顶层仅 ``records`` 一个键，元素为导出行）。"""
    payload = {"records": list(rows)}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return text.encode("utf-8")


def render(fmt: str, rows: Sequence[Dict[str, Any]]) -> Tuple[bytes, str, str]:
    """返回 ``(内容字节, 扩展名, MIME)``。"""
    if fmt == "json":
        return render_json(rows), "json", "application/json"
    return render_csv(rows), "csv", "text/csv"


# ════════════════════════════════════════════════════════════════════
# 文件系统（受 ``EXPORT_DIR`` 约束，**不接受客户端路径**）
# ════════════════════════════════════════════════════════════════════
def export_dir() -> str:
    return str(current_app.config.get("EXPORT_DIR") or "")


def new_file_token() -> str:
    """下载凭证：``secrets.token_hex(16)`` = 32 位十六进制（匹配 ``CHAR(32)``）。"""
    return secrets.token_hex(FILE_TOKEN_BYTES)


def _write_export_file(content: bytes, ext: str) -> str:
    """落盘到 ``EXPORT_DIR`` 下的**服务端生成文件名**（客户端无法指定路径）。"""
    base = export_dir()
    if not base:
        raise OSError("EXPORT_DIR 未配置")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{new_file_token()}.{ext}")
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def safe_download_path(stored: Optional[str]) -> str:
    """把库内 ``file_path`` 收敛为**必须位于 ``EXPORT_DIR`` 内**的真实文件路径。

    防目录穿越（§安全边界）：任何越界路径 → ``404``；文件缺失 → ``410``。
    """
    if not stored:
        raise ApiError(ErrorCode.EXPORT_EXPIRED)
    base = export_dir()
    if not base:
        raise ApiError(ErrorCode.INTERNAL_ERROR)
    base_real = os.path.realpath(base)
    target = os.path.realpath(str(stored))
    try:
        inside = os.path.commonpath([base_real, target]) == base_real
    except ValueError:  # 不同盘符 / 混合绝对与相对路径
        inside = False
    if not inside:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    if not os.path.isfile(target):
        raise ApiError(ErrorCode.EXPORT_EXPIRED)
    return target


def download_filename(job: ExportJob) -> str:
    """``Content-Disposition`` 文件名（服务端生成，**不含用户名 / user_id**）。"""
    ext = "json" if str(job.format) == "json" else "csv"
    day = job.created_at.strftime("%Y%m%d") if job.created_at else now_local().strftime("%Y%m%d")
    return f"{EXPORT_FILENAME_PREFIX}_{day}.{ext}"


def content_type_of(job: ExportJob) -> str:
    return "application/json" if str(job.format) == "json" else "text/csv"


# ════════════════════════════════════════════════════════════════════
# 内部查询
# ════════════════════════════════════════════════════════════════════
def _find_in_progress(db: Session, user_id: int, now: datetime) -> Optional[ExportJob]:
    """是否已有**进行中**（``pending`` / ``ready``）任务。

    ``expired`` / ``purged`` 按时间动态判定 —— 窗口已过的任务**不再阻塞**新导出。
    """
    rows = db.execute(
        select(ExportJob)
        .where(ExportJob.user_id == user_id, ExportJob.status.in_(list(IN_PROGRESS_STATUSES)))
        .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
    ).scalars().all()
    for job in rows:
        if effective_status(job, now) in IN_PROGRESS_STATUSES:
            return job
    return None


def _owned_job(db: Session, user_id: int, export_id: int) -> ExportJob:
    """``WHERE id = ? AND user_id = ?``；非本人 → ``404``（不暴露存在性）。"""
    job = db.execute(
        select(ExportJob).where(ExportJob.id == export_id, ExportJob.user_id == user_id)
    ).scalars().first()
    if job is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    return job


# ════════════════════════════════════════════════════════════════════
# E-01 创建导出任务
# ════════════════════════════════════════════════════════════════════
def create_export(db: Session, cfg: Dict[str, Any], *, user_id: int, session: Any,
                  account: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """E-01：创建导出任务（**同步生成**，返回真实状态）。

    顺序：参数校验 → **二次验密**（安全闸门）→ 进行中冲突 → 取数渲染落盘 → 建任务。
    """
    if not isinstance(payload, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)

    fmt = _parse_format(payload.get("format"))
    metric_types = _parse_metric_types(payload.get("metric_types"))
    start, end = _parse_range(payload)

    password_raw = payload.get("password")
    if _clean(password_raw) is None:
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error("password", FieldErrorCode.REQUIRED, "密码不能为空")
        ])

    now = now_local()

    # ── 二次验密（安全闸门；每会话计数，**不纳入登录锁定**）──
    if not verify_password(normalize_password(password_raw), account.password_hash):
        count = int(session.export_pwd_fail_count or 0) + 1
        session.export_pwd_fail_count = count
        limit = int(cfg.get("VERIFY_MAX_EXPORT") or 3)
        db.commit()
        if count >= limit:
            raise ApiError(ErrorCode.SESSION_VERIFY_ABORTED)
        raise ApiError(ErrorCode.PASSWORD_INVALID)
    # 验密成功 → 计数清零（C3 冻结）
    session.export_pwd_fail_count = 0
    db.commit()

    # ── 进行中冲突 ──
    if _find_in_progress(db, user_id, now) is not None:
        raise ApiError(ErrorCode.EXPORT_IN_PROGRESS)

    # ── 取数 + 渲染 ──
    records = _fetch_records(db, user_id, metric_types, start, end)
    tags_map = _tags_of(db, [int(r.id) for r in records], user_id)
    rows = _rows(records, tags_map)
    content, ext, _mime = render(fmt, rows)

    metric_types_text = ",".join(metric_types) if metric_types else None
    ttl = _ttl_minutes(cfg)
    purge = _purge_minutes(cfg)

    # ── 落盘（失败**不静默**：登记 failed 任务并抛 500）──
    try:
        path = _write_export_file(content, ext)
    except OSError:
        logger.exception("导出文件写入失败（user=%s）", user_id)
        db.add(ExportJob(
            user_id=user_id, format=fmt, metric_types=metric_types_text,
            range_start=start, range_end=end, status="failed",
            file_token=new_file_token(), file_path=None,
            file_size_bytes=None, record_count=None,
            download_expires_at=now + timedelta(minutes=ttl),
            purge_at=now + timedelta(minutes=purge),
            downloaded_at=None, created_at=now,
        ))
        db.commit()
        raise ApiError(ErrorCode.INTERNAL_ERROR)

    job = ExportJob(
        user_id=user_id, format=fmt, metric_types=metric_types_text,
        range_start=start, range_end=end, status="ready",
        file_token=new_file_token(), file_path=path,
        file_size_bytes=len(content), record_count=len(rows),
        download_expires_at=now + timedelta(minutes=ttl),
        purge_at=now + timedelta(minutes=purge),
        downloaded_at=None, created_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "导出任务已创建：export_id=%s format=%s status=%s record_count=%s",
        job.id, job.format, job.status, job.record_count,
    )
    return {
        "export_id": int(job.id),
        "format": job.format,
        "status": effective_status(job),
        "record_count": job.record_count,
        "download_expires_at": format_dt(job.download_expires_at),
        "purge_at": format_dt(job.purge_at),
        "created_at": format_dt(job.created_at),
    }


# ════════════════════════════════════════════════════════════════════
# E-02 导出任务查询
# ════════════════════════════════════════════════════════════════════
def get_export(db: Session, user_id: int, export_id: int) -> Dict[str, Any]:
    """E-02：``WHERE id = ? AND user_id = ?``；非本人 → ``404``。"""
    job = _owned_job(db, user_id, export_id)
    return job_view(job, include_token=True)


# ════════════════════════════════════════════════════════════════════
# E-03 下载导出文件
# ════════════════════════════════════════════════════════════════════
def resolve_download(db: Session, user_id: int, export_id: int,
                     file_token: Optional[str]) -> ExportJob:
    """E-03：``id + user_id + file_token`` **三条件**；返回可下载任务。

    - 任务不存在 / 非本人 / ``file_token`` 不匹配 → ``404 RESOURCE_NOT_FOUND``；
    - 超出 10 分钟窗口 / 已 ``expired`` / ``purged`` / 文件缺失 → ``410 EXPORT_EXPIRED``；
    - 首次下载记录 ``downloaded_at``（窗口内重复下载**不覆盖**首次时间）。
    """
    token = _clean(file_token) or ""
    job = db.execute(
        select(ExportJob).where(
            ExportJob.id == export_id,
            ExportJob.user_id == user_id,
            ExportJob.file_token == token,
        )
    ).scalars().first()
    if job is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    now = now_local()
    if effective_status(job, now) not in DOWNLOADABLE_STATUSES:
        raise ApiError(ErrorCode.EXPORT_EXPIRED)

    path = safe_download_path(job.file_path)

    if job.downloaded_at is None:
        job.downloaded_at = now
        job.status = "downloaded"
        db.commit()
        db.refresh(job)
    logger.info("导出文件已下载：export_id=%s", job.id)
    return job


# ════════════════════════════════════════════════════════════════════
# E-04 导出任务列表（游标分页，created_at DESC）
# ════════════════════════════════════════════════════════════════════
def list_exports(db: Session, user_id: int, args: Any) -> Dict[str, Any]:
    """E-04：``limit`` 默认 20 / 上限 100；``created_at DESC``；**不含** ``file_token`` / ``total``。"""
    limit = parse_limit(args.get("limit"))
    cursor_raw = _clean(args.get("cursor"))

    conditions = [ExportJob.user_id == user_id]
    if cursor_raw is not None:
        cursor_at, cursor_id = decode_cursor(cursor_raw)
        conditions.append(or_(
            ExportJob.created_at < cursor_at,
            and_(ExportJob.created_at == cursor_at, ExportJob.id < cursor_id),
        ))

    rows = list(db.execute(
        select(ExportJob)
        .where(*conditions)
        .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
        .limit(limit + 1)
    ).scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]
    now = now_local()
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, int(last.id))
    return {
        "items": [job_view(j, now, include_token=False) for j in items],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


__all__ = [
    "ALLOWED_FORMATS",
    "EXPORT_COLUMNS",
    "create_export",
    "get_export",
    "resolve_download",
    "list_exports",
    "effective_status",
    "job_view",
    "download_filename",
    "content_type_of",
    "safe_download_path",
]
