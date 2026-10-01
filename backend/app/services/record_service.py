# -*- coding: utf-8 -*-
"""健康记录服务（R-01 ~ R-08）。

依据：《S1-B 第二批 API 接口设计文档》§七（R-01 ~ R-08）、§3.9 ~ §3.14

统一口径：
1. ``user_id`` **只来自 Access Token**（客户端提交 ``user_id`` → 全局守卫 ``400``）。
2. **软删数据全链路不可见**；跨用户 / 不存在 / 已软删 → **统一 404**（不暴露"存在但无权"）。
3. 查询一律 ``WHERE id = ? AND user_id = ?``（**不在应用层比对**，防 TOCTOU）。
4. `recorded_at` 为**未来** → ``422``；时间范围为**半开区间** ``[start, end)``。
5. **派生值不落库**（BMI / 睡眠时长 / 当日累计）。
6. 标签：**编辑时被移除的标签行物理删除**、新增的插入（S1-B 数据库 §9.2）；
   软删**仅随父记录软删同步发生**。

**红线**：只做录入合理性校验（格式 / 精度 / 不可能值 / 字段矛盾）；
**不做**医学判断、**不给**建议、**不产生**任何结论、**不计算**未冻结的派生指标。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode, FieldErrorCode, field_error, validation_error
from app.core.paging import (
    decode_cursor,
    encode_cursor,
    format_dt,
    parse_body_datetime,
    parse_limit,
    parse_range,
)
from app.core.security import now_local, verify_password
from app.core.warnings import soft_warning_payload
from app.models.health_record import HealthRecord
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.services import metric_rules

#: 批量删除「大数量」二次确认阈值（S1-B §七 R-06）
CONFIRM_THRESHOLD = 500
#: 二次确认文字（冻结口径）
CONFIRM_TEXT = "确认删除"

#: ``record`` 视图的固定键（§3.13：未填写字段**保留键**并返回 null）
RECORD_KEYS = (
    "id", "metric_type", "value_1", "value_2", "value_3", "unit",
    "attr_1", "attr_2", "recorded_at", "time_start", "note", "tags", "created_at",
)

#: 可编辑字段（R-04；``metric_type`` **不在其中**）
EDITABLE_FIELDS = (
    "value_1", "value_2", "value_3", "attr_1", "attr_2",
    "recorded_at", "time_start", "tags", "note",
)


# ────────────────────────────── 基础工具 ──────────────────────────────

def _num(value: Optional[Decimal]) -> Optional[Any]:
    """数值输出：整数值输出 ``int``，否则 ``float``（与契约示例一致）。"""
    if value is None:
        return None
    dec = Decimal(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _derive_values(record: HealthRecord) -> Dict[str, Any]:
    """记录的有效字段值（用于校验与合并）。"""
    return {
        "value_1": record.value_1,
        "value_2": record.value_2,
        "value_3": record.value_3,
        "attr_1": record.attr_1,
        "attr_2": record.attr_2,
        "recorded_at": record.recorded_at,
        "time_start": record.time_start,
        "note": record.note,
    }


def _tags_of(db: Session, record_ids: Sequence[int], user_id: int) -> Dict[int, List[str]]:
    """批量取标签（只取未软删行）。"""
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


def _view(record: HealthRecord, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "id": int(record.id),
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


def _find_owned(db: Session, user_id: int, record_id: int) -> HealthRecord:
    """按 ``id + user_id + 未软删`` 定位；否则统一 ``404``。"""
    record = db.execute(
        select(HealthRecord).where(
            HealthRecord.id == record_id,
            HealthRecord.user_id == user_id,
            HealthRecord.is_deleted == 0,
        )
    ).scalars().first()
    if record is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    return record


def _profile_height(db: Session, user_id: int) -> Optional[Decimal]:
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if profile is None or profile.height_cm is None:
        return None
    return Decimal(profile.height_cm)


def derived_for(db: Session, user_id: int, record: HealthRecord) -> Dict[str, Any]:
    """``derived``（**只陈述事实**，按指标返回；均**不落库**）。

    - ``weight`` → ``bmi``
    - ``sleep`` → ``sleep_duration_minutes`` / ``sleep_duration_hours``
    - ``water`` → ``today_total_ml``（服务端本地日 ``[今日00:00:00, 明日00:00:00)``）
    - ``sport`` → ``week_total_minutes`` 依赖健康目标（G 模块）周期口径，**本批不做 G**，故不返回；
    - 其余指标 → ``{}``
    """
    metric = record.metric_type
    if metric == "weight":
        height = _profile_height(db, user_id)
        weight = Decimal(record.value_1) if record.value_1 is not None else None
        bmi = None
        if weight is not None and height is not None and height > 0:
            height_m = height / Decimal("100")
            bmi = float((weight / (height_m * height_m)).quantize(Decimal("0.1")))
        return {"bmi": bmi}
    if metric == "sleep":
        hours = metric_rules.sleep_duration_hours(
            {"time_start": record.time_start, "recorded_at": record.recorded_at}
        )
        if hours is None:
            return {"sleep_duration_minutes": None, "sleep_duration_hours": None}
        return {
            "sleep_duration_minutes": int((hours * 60).to_integral_value()),
            "sleep_duration_hours": float(hours),
        }
    if metric == "water":
        return {"today_total_ml": _today_total_ml(db, user_id, record.recorded_at)}
    return {}


def _today_total_ml(db: Session, user_id: int, anchor: datetime) -> int:
    """当日累计饮水量（半开区间 ``[当日 00:00:00, 次日 00:00:00)``）。"""
    day_start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    total = db.execute(
        select(func.coalesce(func.sum(HealthRecord.value_1), 0)).where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == "water",
            HealthRecord.is_deleted == 0,
            HealthRecord.recorded_at >= day_start,
            HealthRecord.recorded_at < day_end,
        )
    ).scalar()
    return int(Decimal(total or 0))


# ────────────────────────────── 标签维护 ──────────────────────────────

def replace_tags(db: Session, user_id: int, record_id: int, tags: Sequence[str],
                 now: datetime) -> None:
    """R-04 标签**整体替换**：移除的行**物理删除**，新增的插入（S1-B 数据库 §9.2）。"""
    current = db.execute(
        select(RecordTag).where(
            RecordTag.user_id == user_id,
            RecordTag.record_id == record_id,
        )
    ).scalars().all()
    current_map = {row.tag_value: row for row in current}
    wanted = list(dict.fromkeys(tags))
    for tag, row in current_map.items():
        if tag not in wanted:
            db.delete(row)
    for tag in wanted:
        if tag not in current_map:
            db.add(RecordTag(
                user_id=user_id, record_id=record_id, tag_value=tag,
                is_deleted=0, created_at=now,
            ))


def soft_delete_tags(db: Session, user_id: int, record_ids: Iterable[int], now: datetime) -> int:
    """父记录软删时**同步软删**其标签。"""
    ids = list(record_ids)
    if not ids:
        return 0
    rows = db.execute(
        select(RecordTag).where(
            RecordTag.user_id == user_id,
            RecordTag.record_id.in_(ids),
            RecordTag.is_deleted == 0,
        )
    ).scalars().all()
    for row in rows:
        row.is_deleted = 1
        row.deleted_at = now
    return len(rows)


# ────────────────────────────── 请求归一化 ──────────────────────────────

def _normalize_metric(metric_type: Any) -> str:
    metric = str(metric_type or "").strip()
    if metric not in metric_rules.METRIC_TYPES:
        raise validation_error(
            [field_error("metric_type", FieldErrorCode.INVALID_FORMAT, "指标类型不在允许范围内")]
        )
    return metric


def _check_unit(metric: str, unit: Any) -> None:
    """单位由服务端填充；客户端传入不一致 → ``422``。"""
    if unit is None:
        return
    text = str(unit).strip()
    if text and text != metric_rules.METRIC_UNIT[metric]:
        raise validation_error(
            [field_error("unit", FieldErrorCode.INVALID_FORMAT, "单位与指标不一致")]
        )


def _normalize_note(note: Any) -> Optional[str]:
    if note is None:
        return None
    text = str(note).strip()
    return text or None


def _future_guard(recorded_at: Optional[datetime]) -> None:
    if recorded_at is not None and recorded_at > now_local():
        raise validation_error(
            [field_error("recorded_at", FieldErrorCode.INVALID_FORMAT, "记录时间不得晚于当前时间")]
        )


def _check_tags(metric: str, tags: Any) -> List[str]:
    if tags is None:
        return []
    if metric != "mood":
        raise validation_error(
            [field_error("tags", FieldErrorCode.INVALID_FORMAT, "该指标不支持标签")]
        )
    normalized = metric_rules.normalize_tags(tags)
    problem = metric_rules.validate_tags(normalized)
    if problem:
        raise validation_error(
            [field_error("tags", FieldErrorCode.INVALID_FORMAT, problem)]
        )
    return normalized


# ────────────────────────────── R-01 新增 ──────────────────────────────

def create_record(db: Session, user_id: int, payload: Dict[str, Any],
                  acknowledge: bool) -> Tuple[str, Dict[str, Any]]:
    """R-01：新增一条记录。

    返回 ``(kind, data)``，``kind`` ∈ ``{"written", "soft_warning"}``。
    """
    metric = _normalize_metric(payload.get("metric_type"))
    _check_unit(metric, payload.get("unit"))

    present: Set[str] = {k for k in payload if k != "acknowledge_warnings"}
    recorded_raw = payload.get("recorded_at")
    recorded_at = parse_body_datetime("recorded_at", recorded_raw) if recorded_raw is not None else None
    if recorded_at is None and metric != "sleep":
        recorded_at = now_local()          # 默认当前时间（§七 R-01）
    time_start = parse_body_datetime("time_start", payload.get("time_start"))
    _future_guard(recorded_at)

    values: Dict[str, Any] = {
        "value_1": payload.get("value_1"),
        "value_2": payload.get("value_2"),
        "value_3": payload.get("value_3"),
        "attr_1": payload.get("attr_1"),
        "attr_2": payload.get("attr_2"),
        "recorded_at": recorded_at,
        "time_start": time_start,
        "note": _normalize_note(payload.get("note")),
        "tags": None,
    }
    values["attr_1"], values["attr_2"] = metric_rules.normalize_attr(
        metric, values["attr_1"], values["attr_2"]
    )
    tags = _check_tags(metric, payload.get("tags"))
    values["tags"] = tags if tags else None

    errors, warnings = metric_rules.validate_record(metric, values, present=present)
    if errors:
        raise validation_error(errors)
    if warnings and not acknowledge:
        return "soft_warning", soft_warning_payload(warnings)

    now = now_local()
    record = HealthRecord(
        user_id=user_id,
        metric_type=metric,
        value_1=values["value_1"],
        value_2=values["value_2"],
        value_3=values["value_3"],
        unit=metric_rules.METRIC_UNIT[metric],
        attr_1=values["attr_1"],
        attr_2=values["attr_2"],
        recorded_at=recorded_at,
        time_start=values["time_start"],
        note=values["note"],
        is_deleted=0,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.flush()
    if tags:
        replace_tags(db, user_id, int(record.id), tags, now)
    db.commit()
    db.refresh(record)

    tags_map = _tags_of(db, [int(record.id)], user_id)
    return "written", {
        "record": _view(record, tags_map.get(int(record.id), [])),
        "derived": derived_for(db, user_id, record),
        "warnings": list(warnings),
    }


# ────────────────────────────── R-02 列表 / R-07 计数 ──────────────────────────────

def _query_metric(raw: Optional[str]) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        return None
    metric = str(raw).strip()
    if metric not in metric_rules.METRIC_TYPES:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return metric


def _filtered(db: Session, user_id: int, metric: Optional[str],
              start: Optional[datetime], end: Optional[datetime]):
    conditions = [HealthRecord.user_id == user_id, HealthRecord.is_deleted == 0]
    if metric is not None:
        conditions.append(HealthRecord.metric_type == metric)
    if start is not None:
        conditions.append(HealthRecord.recorded_at >= start)
    if end is not None:
        conditions.append(HealthRecord.recorded_at < end)
    return conditions


def list_records(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """R-02：游标分页列表（**不返回 total**）。"""
    metric = _query_metric(args.get("metric_type"))
    start, end = parse_range(args.get("start"), args.get("end"))
    limit = parse_limit(args.get("limit"))
    cursor_raw = args.get("cursor")

    conditions = _filtered(db, user_id, metric, start, end)
    if cursor_raw is not None and str(cursor_raw).strip() != "":
        cursor_at, cursor_id = decode_cursor(str(cursor_raw))
        # keyset：recorded_at DESC, id DESC 的严格后继
        conditions.append(
            (HealthRecord.recorded_at < cursor_at)
            | ((HealthRecord.recorded_at == cursor_at) & (HealthRecord.id < cursor_id))
        )

    rows = db.execute(
        select(HealthRecord)
        .where(*conditions)
        .order_by(HealthRecord.recorded_at.desc(), HealthRecord.id.desc())
        .limit(limit + 1)
    ).scalars().all()

    has_more = len(rows) > limit
    items_rows = rows[:limit]
    tags_map = _tags_of(db, [int(r.id) for r in items_rows], user_id)
    items = [_view(r, tags_map.get(int(r.id), [])) for r in items_rows]

    next_cursor = None
    if has_more and items_rows:
        last = items_rows[-1]
        next_cursor = encode_cursor(last.recorded_at, int(last.id))

    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


def count_records(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """R-07：条数统计（**只返回条数**，软删不计入）。"""
    metric = _query_metric(args.get("metric_type"))
    start, end = parse_range(args.get("start"), args.get("end"))
    total = db.execute(
        select(func.count(HealthRecord.id)).where(
            *_filtered(db, user_id, metric, start, end)
        )
    ).scalar()
    return {"count": int(total or 0)}


# ────────────────────────────── R-03 详情 ──────────────────────────────

def get_record(db: Session, user_id: int, record_id: int) -> Dict[str, Any]:
    """R-03：详情（``id + user_id`` 双条件）。"""
    record = _find_owned(db, user_id, record_id)
    tags_map = _tags_of(db, [int(record.id)], user_id)
    return {
        "record": _view(record, tags_map.get(int(record.id), [])),
        "derived": derived_for(db, user_id, record),
    }


# ────────────────────────────── R-04 编辑 ──────────────────────────────

def patch_record(db: Session, user_id: int, record_id: int, payload: Dict[str, Any],
                 acknowledge: bool) -> Tuple[str, Dict[str, Any]]:
    """R-04：局部更新；``metric_type`` 一旦出现（**即使值相同**）→ ``422``。"""
    record = _find_owned(db, user_id, record_id)
    if "metric_type" in payload:
        raise validation_error(
            [field_error("metric_type", FieldErrorCode.INVALID_FORMAT, "指标类型不允许修改")]
        )
    metric = record.metric_type
    _check_unit(metric, payload.get("unit"))

    present: Set[str] = {k for k in payload if k != "acknowledge_warnings"}
    effective = _derive_values(record)

    if "recorded_at" in payload:
        effective["recorded_at"] = parse_body_datetime("recorded_at", payload.get("recorded_at"))
    if "time_start" in payload:
        effective["time_start"] = parse_body_datetime("time_start", payload.get("time_start"))
    for field in ("value_1", "value_2", "value_3", "note"):
        if field in payload:
            effective[field] = _normalize_note(payload.get(field)) if field == "note" else payload.get(field)
    if "attr_1" in payload or "attr_2" in payload:
        a1 = payload.get("attr_1", record.attr_1)
        a2 = payload.get("attr_2", record.attr_2)
        effective["attr_1"], effective["attr_2"] = metric_rules.normalize_attr(metric, a1, a2)

    tags: Optional[List[str]] = None
    if "tags" in payload:
        tags = _check_tags(metric, payload.get("tags"))
        effective["tags"] = tags or None

    _future_guard(effective.get("recorded_at"))
    errors, warnings = metric_rules.validate_record(
        metric, effective, present=present, forbid_check=True
    )
    if errors:
        raise validation_error(errors)
    if warnings and not acknowledge:
        return "soft_warning", soft_warning_payload(warnings)

    now = now_local()
    record.value_1 = effective.get("value_1")
    record.value_2 = effective.get("value_2")
    record.value_3 = effective.get("value_3")
    record.attr_1 = effective.get("attr_1")
    record.attr_2 = effective.get("attr_2")
    record.recorded_at = effective.get("recorded_at")
    record.time_start = effective.get("time_start")
    record.note = effective.get("note")
    record.updated_at = now
    if tags is not None:
        replace_tags(db, user_id, int(record.id), tags, now)
    db.commit()
    db.refresh(record)

    tags_map = _tags_of(db, [int(record.id)], user_id)
    return "written", {
        "record": _view(record, tags_map.get(int(record.id), [])),
        "derived": derived_for(db, user_id, record),
        "warnings": list(warnings),
    }


# ────────────────────────────── R-05 单条删除 ──────────────────────────────

def delete_record(db: Session, user_id: int, record_id: int) -> Dict[str, Any]:
    """R-05：软删（``is_deleted=1`` + ``deleted_at``），标签**同步软删**。"""
    record = _find_owned(db, user_id, record_id)
    now = now_local()
    record.is_deleted = 1
    record.deleted_at = now
    record.updated_at = now
    soft_delete_tags(db, user_id, [int(record.id)], now)
    db.commit()
    return {"deleted_count": 1}


# ────────────────────────────── R-06 批量删除 ──────────────────────────────

def batch_delete(db: Session, account: UserAccount, payload: Dict[str, Any]) -> Dict[str, Any]:
    """R-06：按指标 + 时间范围批量软删（密码验证 + 条数一致性 + 大数量二次确认）。"""
    user_id = int(account.id)
    metric = _query_metric(payload.get("metric_type"))
    start, end = parse_range(payload.get("start"), payload.get("end"))

    # ① 密码验证（**不纳入登录锁定计数**）
    if not verify_password(str(payload.get("password") or ""), account.password_hash):
        raise ApiError(ErrorCode.PASSWORD_INVALID)

    # ② 服务端 COUNT 为准（**不采信客户端传值**）
    actual = int(db.execute(
        select(func.count(HealthRecord.id)).where(
            *_filtered(db, user_id, metric, start, end)
        )
    ).scalar() or 0)

    # ③ 条数一致性（用户看到的条数已过期 → 提示刷新）
    expected = payload.get("expected_count")
    if expected is not None and int(expected) != actual:
        raise ApiError(ErrorCode.COUNT_MISMATCH,
                       data={"expected_count": int(expected), "actual_count": actual})

    # ④ 大数量二次确认（阈值按**实际条数**）
    if actual >= CONFIRM_THRESHOLD and str(payload.get("confirm_text") or "").strip() != CONFIRM_TEXT:
        raise validation_error(
            [field_error("confirm_text", FieldErrorCode.INVALID_FORMAT,
                         f"删除条数较多，需填写确认文字「{CONFIRM_TEXT}」")]
        )

    if actual == 0:
        return {"deleted_count": 0}

    now = now_local()
    ids = [int(x) for x in db.execute(
        select(HealthRecord.id).where(
            *_filtered(db, user_id, metric, start, end)
        )
    ).scalars().all()]
    for chunk_start in range(0, len(ids), 500):
        chunk = ids[chunk_start:chunk_start + 500]
        rows = db.execute(
            select(HealthRecord).where(HealthRecord.id.in_(chunk),
                                       HealthRecord.user_id == user_id,
                                       HealthRecord.is_deleted == 0)
        ).scalars().all()
        for row in rows:
            row.is_deleted = 1
            row.deleted_at = now
            row.updated_at = now
        soft_delete_tags(db, user_id, chunk, now)
    db.commit()
    return {"deleted_count": actual}


# ────────────────────────────── R-08 选项 ──────────────────────────────

def list_options() -> Dict[str, Any]:
    """R-08：静态枚举字典（**不访问数据库**、**无动态指标体系**）。"""
    return metric_rules.options_payload()


# ────────────────────────────── 幂等辅助 ──────────────────────────────

def remember_idempotent(user_id: int, key: Optional[str], body: Any, status: int,
                        code: str, message: str, data: Any) -> None:
    from app.core import idempotency

    idempotency.remember(user_id, key, body, status, code, message, data)


def lookup_idempotent(user_id: int, key: Optional[str], body: Any) -> Optional[Dict[str, Any]]:
    from app.core import idempotency

    return idempotency.lookup(user_id, key, body)


__all__ = [
    "create_record",
    "list_records",
    "count_records",
    "get_record",
    "patch_record",
    "delete_record",
    "batch_delete",
    "list_options",
    "derived_for",
    "replace_tags",
    "soft_delete_tags",
    "remember_idempotent",
    "lookup_idempotent",
    "RECORD_KEYS",
    "EDITABLE_FIELDS",
    "CONFIRM_THRESHOLD",
    "CONFIRM_TEXT",
]
