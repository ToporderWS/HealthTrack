# -*- coding: utf-8 -*-
"""数据管理服务（本批实现 **D-01 / D-02**）。

依据（**逐条落实，不发明字段**）：
- 《S1-B 第二批 API 接口设计文档》§十一「数据管理 API（模块 D，2 个）」（1760~1856 行）
- 《S1-B 数据库设计文档》§12.5「清空全部数据 —— 范围矩阵（D-2 修正结论）」（914~965 行）
- 《S1-D 技术方案最终冻结》§6.3（``user_id`` 只来自 Access Token；隔离口径）

冻结口径：
- **D-01 数据总览**：只返回**条数 / 最早-最晚时间 / 已设目标数 / 档案健康字段填写数**；
  **不返回任何数值统计**（数值统计属趋势页 S-03）；软删数据一律不计入。
  无数据时 ``total_records = 0`` 且 ``by_metric = []``（**不逐类返回 0 行**）。
- **D-02 清空全部数据**：**三重确认**（确认文字「确认删除」+ 登录密码 + 声明不可恢复）；
  **单事务**，任何一步失败**整体回滚**（不得出现"清一半"）；**保留账号**；
  范围严格 4 项（见 :data:`CLEAR_SCOPE`），**不接受**任何范围扩展参数。
  保留清单（**严禁删除 / 不软删 / 不改写**，边界第 11 条）：``user_account`` 账号行、
  ``user_profile`` 档案行（含 ``nickname`` / ``gender`` / ``birth_date``）、
  ``user_session`` 会话、``login_failure_state`` 登录失败状态、
  ``export_job`` 导出任务与既有导出文件、系统日志 —— 以上**一律不删除**。
- **C1 冻结**：密码错误 → ``422 PASSWORD_INVALID``；**不累计失败次数、不触发锁定、不返回 429**。
- **越权边界**：``user_id`` 只能来自 Access Token；所有读写恒带 ``user_id`` 条件。
- **日志**：不记录健康数值 / 用户名 / ``user_id`` 级别的明细内容。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    ApiError,
    ErrorCode,
    FieldErrorCode,
    field_error,
    validation_error,
)
from app.core.paging import format_dt
from app.core.security import normalize_password, now_local, verify_password
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.services import goal_service, metric_rules, record_service

logger = logging.getLogger(__name__)

#: D-02 确认文字 —— **复用 R-06 冻结常量**（单一数据源，不重复定义文案）
CONFIRM_TEXT = record_service.CONFIRM_TEXT

#: D-02 执行范围（响应 ``scope`` **逐字回显**，顺序冻结，不得增删或调序）
CLEAR_SCOPE: Tuple[str, ...] = (
    "health_records",
    "record_tags",
    "goals",
    "profile_health_fields",
)

#: ``user_profile`` 的 **6 个健康字段**（D-02 清空对象）
#: **不含** ``nickname`` / ``gender`` / ``birth_date``（冻结：保留不动）
PROFILE_HEALTH_FIELDS: Tuple[str, ...] = (
    "height_cm",
    "initial_weight_kg",
    "blood_type",
    "medical_history",
    "allergy_history",
    "medication_notes",
)

#: D-01 ``profile.health_fields_total``（冻结为 6）
HEALTH_FIELDS_TOTAL = 6

#: D-02 成功文案模板（冻结形态：含实际清除条数 + 账号保留）
CLEAR_MESSAGE = "已清除 {count} 条记录。账号保留，数据已按规则清除"


# ════════════════════════════════════════════════════════════════════
# D-01 数据总览
# ════════════════════════════════════════════════════════════════════
def _total_records(db: Session, user_id: int) -> int:
    """活跃记录总数（``user_id`` + ``is_deleted = 0``）。"""
    return int(db.execute(
        select(func.count(HealthRecord.id)).where(
            HealthRecord.user_id == user_id,
            HealthRecord.is_deleted == 0,
        )
    ).scalar() or 0)


def _goal_counts(db: Session, user_id: int) -> Dict[str, int]:
    """已设目标数：``active_count``（status=1）/ ``paused_count``（status=0），只含未软删。"""
    rows = db.execute(
        select(HealthGoal.status, func.count(HealthGoal.id))
        .where(HealthGoal.user_id == user_id, HealthGoal.is_deleted == 0)
        .group_by(HealthGoal.status)
    ).all()
    active = 0
    paused = 0
    for status, count in rows:
        value = int(status)
        if value == goal_service.STATUS_ONGOING:
            active += int(count)
        elif value == goal_service.STATUS_PAUSED:
            paused += int(count)
    return {"active_count": active, "paused_count": paused}


def _profile_counts(db: Session, user_id: int) -> Dict[str, int]:
    """档案健康字段填写数（6 个字段中**非 NULL** 的个数）。"""
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if profile is None:
        return {"health_fields_filled": 0, "health_fields_total": HEALTH_FIELDS_TOTAL}
    filled = sum(
        1 for field in PROFILE_HEALTH_FIELDS if getattr(profile, field) is not None
    )
    return {"health_fields_filled": filled, "health_fields_total": HEALTH_FIELDS_TOTAL}


def summary(db: Session, user_id: int) -> Dict[str, Any]:
    """D-01：数据总览（**只返回条数与时间范围**，不做任何数值统计）。

    - ``by_metric`` 按 :data:`metric_rules.METRIC_TYPES` **固定顺序**输出，
      **只含有数据的指标**（无数据不返回 0 行）；
    - ``first_recorded_at`` / ``last_recorded_at`` 取该指标活跃记录的最早 / 最晚发生时间；
    - 恒带 ``user_id`` + ``is_deleted = 0``（软删数据不计入）。
    """
    rows = db.execute(
        select(
            HealthRecord.metric_type,
            func.count(HealthRecord.id),
            func.min(HealthRecord.recorded_at),
            func.max(HealthRecord.recorded_at),
        )
        .where(HealthRecord.user_id == user_id, HealthRecord.is_deleted == 0)
        .group_by(HealthRecord.metric_type)
    ).all()

    grouped: Dict[str, Tuple[int, Any, Any]] = {}
    for metric_type, count, first_at, last_at in rows:
        grouped[str(metric_type)] = (int(count), first_at, last_at)

    by_metric: List[Dict[str, Any]] = []
    for metric_type in metric_rules.METRIC_TYPES:      # 固定顺序（C3 冻结）
        item = grouped.get(metric_type)
        if item is None:
            continue                                   # 只返回有数据的指标
        count, first_at, last_at = item
        by_metric.append({
            "metric_type": metric_type,
            "count": count,
            "first_recorded_at": format_dt(first_at),
            "last_recorded_at": format_dt(last_at),
        })

    return {
        "total_records": _total_records(db, user_id),
        "by_metric": by_metric,
        "goals": _goal_counts(db, user_id),
        "profile": _profile_counts(db, user_id),
    }


# ════════════════════════════════════════════════════════════════════
# D-02 清空全部数据
# ════════════════════════════════════════════════════════════════════
def clear_message(deleted_records: int) -> str:
    """D-02 成功文案（冻结形态）。"""
    return CLEAR_MESSAGE.format(count=int(deleted_records))


def _validate_confirm(payload: Dict[str, Any]) -> None:
    """三重确认中的「确认文字」与「不可恢复声明」；不合法 → ``422 VALIDATION_FAILED``。"""
    errors: List[Dict[str, Any]] = []

    text = payload.get("confirm_text")
    if not isinstance(text, str) or text.strip() != CONFIRM_TEXT:
        errors.append(field_error(
            "confirm_text", FieldErrorCode.INVALID_FORMAT, "确认文字不正确"
        ))

    # ★ 必须是**布尔 true**（字符串 "true" 不算已确认）
    if payload.get("acknowledge_irreversible") is not True:
        errors.append(field_error(
            "acknowledge_irreversible", FieldErrorCode.NOT_ACCEPTED,
            "请先确认删除后无法恢复",
        ))

    if errors:
        raise validation_error(errors)


def _verify_login_password(account: UserAccount, payload: Dict[str, Any]) -> None:
    """三重确认中的「登录密码」。

    **C1 冻结**：密码错误 → ``422 PASSWORD_INVALID``；
    **不累计失败次数、不触发锁定、不返回 429**（与登录锁定 / 导出验密计数完全无关）。
    """
    raw = payload.get("password")
    if not isinstance(raw, str) or not raw.strip():
        raise validation_error([
            field_error("password", FieldErrorCode.REQUIRED, "密码不能为空")
        ])
    if not verify_password(normalize_password(raw), account.password_hash):
        raise ApiError(ErrorCode.PASSWORD_INVALID)


def _soft_delete_records(db: Session, user_id: int, now: Any) -> int:
    """``health_record`` 全量软删（``is_deleted=1`` + ``deleted_at``）。"""
    rows = db.execute(
        select(HealthRecord).where(
            HealthRecord.user_id == user_id,
            HealthRecord.is_deleted == 0,
        )
    ).scalars().all()
    for row in rows:
        row.is_deleted = 1
        row.deleted_at = now
        row.updated_at = now
    return len(rows)


def _soft_delete_tags(db: Session, user_id: int, now: Any) -> int:
    """``record_tag`` **随主记录同步软删**（全部活跃标签）。"""
    rows = db.execute(
        select(RecordTag).where(
            RecordTag.user_id == user_id,
            RecordTag.is_deleted == 0,
        )
    ).scalars().all()
    for row in rows:
        row.is_deleted = 1
        row.deleted_at = now
    return len(rows)


def _soft_delete_goals(db: Session, user_id: int, now: Any) -> int:
    """``health_goal`` 全量软删 + ``deleted_marker = id``（释放唯一约束，可立即重建）。"""
    rows = db.execute(
        select(HealthGoal).where(
            HealthGoal.user_id == user_id,
            HealthGoal.is_deleted == 0,
        )
    ).scalars().all()
    for row in rows:
        row.is_deleted = 1
        row.deleted_at = now
        row.deleted_marker = int(row.id)
        row.updated_at = now
    return len(rows)


def _clear_profile_health_fields(db: Session, user_id: int, now: Any) -> int:
    """``user_profile`` **仅置空 6 个健康字段**；档案行与昵称 / 性别 / 出生日期保留。

    返回**被清空前非 NULL** 的字段个数（= 响应 ``profile_health_fields_cleared``）。
    """
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if profile is None:
        return 0
    cleared = 0
    for field in PROFILE_HEALTH_FIELDS:
        if getattr(profile, field) is not None:
            cleared += 1
        setattr(profile, field, None)
    profile.updated_at = now
    return cleared


def clear_all_data(db: Session, user_id: int, account: UserAccount,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
    """D-02：清空当前用户的全部业务数据（**单事务**；保留账号）。

    顺序：参数三重确认 → 单事务内 4 类清理 → ``commit``；
    任何异常 → ``rollback`` → ``500 INTERNAL_ERROR``（**整体回滚，不得清一半**）。
    """
    if not isinstance(payload, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)

    _validate_confirm(payload)
    _verify_login_password(account, payload)

    now = now_local()
    try:
        deleted_records = _soft_delete_records(db, user_id, now)
        deleted_tags = _soft_delete_tags(db, user_id, now)
        deleted_goals = _soft_delete_goals(db, user_id, now)
        cleared = _clear_profile_health_fields(db, user_id, now)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("清空数据失败，已整体回滚（user=%s）", user_id)
        raise ApiError(ErrorCode.INTERNAL_ERROR)

    logger.info(
        "数据已清空：deleted_records=%s deleted_tags=%s deleted_goals=%s cleared_fields=%s",
        deleted_records, deleted_tags, deleted_goals, cleared,
    )
    return {
        "deleted_records": deleted_records,
        "deleted_tags": deleted_tags,
        "deleted_goals": deleted_goals,
        "profile_health_fields_cleared": cleared,
        "account_kept": True,
        "scope": list(CLEAR_SCOPE),
    }


__all__ = [
    "CLEAR_MESSAGE",
    "CLEAR_SCOPE",
    "CONFIRM_TEXT",
    "HEALTH_FIELDS_TOTAL",
    "PROFILE_HEALTH_FIELDS",
    "clear_all_data",
    "clear_message",
    "summary",
]
