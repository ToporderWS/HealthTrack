# -*- coding: utf-8 -*-
"""健康目标服务（G-01 ~ G-06）。

依据：
- 《S1-B 第二批 API 接口设计文档》§八 G-01 ~ G-06
- 《S1-B 数据库设计文档》§6.6 ``health_goal``（唯一索引 ``uk_goal_user_type_active``）
- 《S0-产品规划报告》§8.1（完成度算法，见 ``goal_progress``）

统一口径：
1. ``user_id`` **只来自 Access Token**（客户端提交 ``user_id`` → 全局守卫 ``400``）。
2. **软删数据全链路不可见**；跨用户 / 不存在 / 已软删 → **统一 404**（不泄露"存在但无权"）。
3. 查询一律 ``WHERE id = ? AND user_id = ?``（**不在应用层比对**，防 TOCTOU）。
4. ``period_type`` / ``unit`` **由服务端按 ``goal_type`` 强制**；客户端传值不一致 → ``422``。
5. 软删**三件事必须齐全**（``is_deleted`` / ``deleted_at`` / ``deleted_marker = id``）；
   漏写 ``deleted_marker`` 将导致唯一约束无法释放 → 用户**永久无法重建同类型目标**。
6. **派生值不落库**（完成度 / 达标率实时算，见 ``goal_progress``）。

**红线**：目标值**一律由用户自设**；系统**不提供任何医学推荐值 / 默认阈值 / 目标建议**；
区间表**只用于识别"疑似录入错误"**（软提示）与"不可能值"（硬拦截），**不是医学参考区间**。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode, FieldErrorCode, field_error, validation_error
from app.core.paging import DATE_FORMAT, DATETIME_FORMAT
from app.core.security import now_local
from app.core.warnings import out_of_range, soft_warning_payload
from app.models.health_goal import HealthGoal
from app.services import profile_service

#: 允许的 4 类目标（受控枚举，§八 G-02）
GOAL_TYPES: Tuple[str, ...] = ("weight", "water", "sport", "sleep")

#: ``goal_type`` → ``period_type``（**服务端强制**，客户端不一致 → 422）
PERIOD_BY_TYPE: Dict[str, str] = {
    "weight": "once",
    "water": "daily",
    "sport": "weekly",
    "sleep": "daily",
}

#: ``goal_type`` → 单位（**服务端填充**；``sport`` 的单位随 ``attr_1``）
UNIT_BY_TYPE: Dict[str, str] = {
    "weight": "kg",
    "water": "ml",
    "sleep": "hour",
}

#: ``sport`` 允许的计量方式：``count``=周次数，``min``=周分钟
SPORT_ATTRS: Tuple[str, ...] = ("count", "min")
SPORT_UNITS: Dict[str, str] = {"count": "count", "min": "min"}

#: ``status`` 取值（1=进行中，0=已暂停）
STATUS_ONGOING = 1
STATUS_PAUSED = 0
#: ``status`` → 中性 ``status_text``（**不含任何评判词**）
STATUS_TEXT: Dict[int, str] = {STATUS_ONGOING: "ongoing", STATUS_PAUSED: "paused"}
#: 历史（已软删）目标的 ``status_text``（中性值，**不泄露软删字段**）
ARCHIVED_TEXT = "archived"

#: 周期 → ``period_label``（G-07 使用，中性英文标记）
PERIOD_LABEL: Dict[str, str] = {"once": "overall", "daily": "today", "weekly": "this_week"}

#: ``goal_type`` → 允许的最大小数位（与第三批 ``metric_rules`` 精度口径一致）
TARGET_DECIMALS: Dict[str, int] = {"weight": 1, "water": 0, "sleep": 1, "sport": 0}

#: 「区间」表示：``(下界, 下界是否含, 上界, 上界是否含)``；``None`` 表示无界
Range = Tuple[Optional[str], bool, Optional[str], bool]

#: **硬拦截** 区间（超出即"不可能值" → 422；来源 开工方案 §六，人工拍板 D-G6）
HARD_RANGE: Dict[str, Range] = {
    "weight": ("0", False, "500", True),
    "water": ("0", False, "20000", True),
    "sleep": ("0", False, "24", True),
}
#: **硬拦截** 区间（``sport`` 随 ``attr_1``）
HARD_SPORT_RANGE: Dict[str, Range] = {
    "count": ("0", False, "70", True),
    "min": ("0", False, "10080", True),
}
#: **软提示** 区间（超出 → HTTP 200 ``SOFT_WARNING``，**本次不写入**）
SOFT_RANGE: Dict[str, Range] = {
    "weight": ("20", True, "300", True),
    "water": ("100", True, "5000", True),
    "sleep": ("1", True, "16", True),
}
#: **软提示** 区间（``sport`` 随 ``attr_1``）
SOFT_SPORT_RANGE: Dict[str, Range] = {
    "count": ("1", True, "14", True),
    "min": ("1", True, "600", True),
}

#: ``start_weight_kg`` 硬拦截区间（仅体重目标；``Numeric(5,1)``）
START_WEIGHT_HARD: Range = ("0", False, "500", True)


# ────────────────────────────── 基础工具 ──────────────────────────────

def _dec(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _num(value: Optional[Decimal]) -> Optional[Any]:
    """数值输出：整数值输出 ``int``，否则 ``float``（与契约示例一致）。"""
    if value is None:
        return None
    dec = Decimal(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _check_range(value: Any, rng: Range) -> bool:
    """``True`` = 落在区间内。"""
    num = _dec(value)
    if num is None:
        return False
    lo, lo_inc, hi, hi_inc = rng
    if lo is not None:
        low = _dec(lo)
        if num < low or (num == low and not lo_inc):
            return False
    if hi is not None:
        high = _dec(hi)
        if num > high or (num == high and not hi_inc):
            return False
    return True


def _too_many_decimals(value: Any, allowed: int) -> bool:
    """小数位是否超出业务精度（先 ``normalize()`` 去除无意义尾随零）。"""
    num = _dec(value)
    if num is None:
        return False
    num = num.normalize()
    if num == num.to_integral_value():
        return False
    if allowed <= 0:
        return True
    return -num.as_tuple().exponent > allowed


def _parse_date(field: str, raw: Any) -> Optional[date]:
    """日期字段：仅接受 ``YYYY-MM-DD``；失败 → ``422``。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        raise validation_error(
            [field_error(field, FieldErrorCode.INVALID_FORMAT, "日期格式应为 YYYY-MM-DD")]
        )


def unit_for(goal_type: str, attr_1: Optional[str]) -> str:
    """目标单位（``sport`` 随 ``attr_1``；其余为固定值）。"""
    if goal_type == "sport":
        return SPORT_UNITS.get(str(attr_1 or ""), "")
    return UNIT_BY_TYPE[goal_type]


def _normalize_goal_type(raw: Any) -> str:
    goal_type = str(raw or "").strip()
    if goal_type not in GOAL_TYPES:
        raise validation_error(
            [field_error("goal_type", FieldErrorCode.INVALID_FORMAT, "目标类型不在允许范围内")]
        )
    return goal_type


def _normalize_attr1(raw: Any) -> Optional[str]:
    text = raw.strip() if isinstance(raw, str) else raw
    return text or None


def _goal_view(goal: HealthGoal, archived: bool = False) -> Dict[str, Any]:
    """目标的对外视图（``is_deleted`` / ``deleted_marker`` **不暴露**）。"""
    return {
        "id": int(goal.id),
        "goal_type": goal.goal_type,
        "period_type": goal.period_type,
        "target_value": _num(goal.target_value),
        "unit": goal.unit,
        "attr_1": goal.attr_1,
        "start_weight_kg": _num(goal.start_weight_kg),
        "start_date": goal.start_date.strftime(DATE_FORMAT) if goal.start_date else None,
        "target_date": goal.target_date.strftime(DATE_FORMAT) if goal.target_date else None,
        "status": int(goal.status),
        "status_text": ARCHIVED_TEXT if archived else STATUS_TEXT.get(int(goal.status), "ongoing"),
        "created_at": goal.created_at.strftime(DATETIME_FORMAT) if goal.created_at else None,
    }


def find_owned_goal(db: Session, user_id: int, goal_id: int) -> HealthGoal:
    """按 ``id + user_id + 未软删`` 定位；否则统一 ``404``。"""
    goal = db.execute(
        select(HealthGoal).where(
            HealthGoal.id == goal_id,
            HealthGoal.user_id == user_id,
            HealthGoal.is_deleted == 0,
        )
    ).scalars().first()
    if goal is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    return goal


def _active_exists(db: Session, user_id: int, goal_type: str,
                   exclude_id: Optional[int] = None) -> bool:
    """同用户同类型**未软删目标**是否存在（唯一约束口径）。"""
    stmt = select(HealthGoal.id).where(
        HealthGoal.user_id == user_id,
        HealthGoal.goal_type == goal_type,
        HealthGoal.is_deleted == 0,
    )
    if exclude_id is not None:
        stmt = stmt.where(HealthGoal.id != exclude_id)
    return db.execute(stmt).scalars().first() is not None


# ────────────────────────────── 查询参数解析 ──────────────────────────────

def query_goal_type(raw: Any) -> Optional[str]:
    """``goal_type`` 查询参数：不传 = 全部；非法值 → ``400 INVALID_PARAM``。"""
    if raw is None or str(raw).strip() == "":
        return None
    goal_type = str(raw).strip()
    if goal_type not in GOAL_TYPES:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return goal_type


def query_bool(args: Dict[str, Any], name: str, default: bool) -> bool:
    """布尔查询参数（``true/false`` / ``1/0`` / ``yes/no``）；非法 → ``400``。"""
    raw = args.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ApiError(ErrorCode.INVALID_PARAM)


def query_int(args: Dict[str, Any], name: str) -> Optional[int]:
    """整数查询参数；非法 → ``400 INVALID_PARAM``。"""
    raw = args.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError(ErrorCode.INVALID_PARAM)


# ────────────────────────────── G-01 列表 ──────────────────────────────

def list_goals(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """G-01：目标列表（**不分页**）。

    - 在用目标：``is_deleted=0``，**显式** ``ORDER BY goal_type ASC``；
    - ``include_paused=false`` → 仅 ``status=1``；
    - ``include_history=true`` → 追加已软删行（``created_at DESC, id DESC``，**只读展示**）。
    """
    goal_type = query_goal_type(args.get("goal_type"))
    include_paused = query_bool(args, "include_paused", True)
    include_history = query_bool(args, "include_history", False)

    conditions = [HealthGoal.user_id == user_id, HealthGoal.is_deleted == 0]
    if goal_type is not None:
        conditions.append(HealthGoal.goal_type == goal_type)
    if not include_paused:
        conditions.append(HealthGoal.status == STATUS_ONGOING)

    rows = db.execute(
        select(HealthGoal)
        .where(*conditions)
        .order_by(HealthGoal.goal_type.asc(), HealthGoal.id.asc())
    ).scalars().all()
    items = [_goal_view(row) for row in rows]

    if include_history:
        history_conditions = [HealthGoal.user_id == user_id, HealthGoal.is_deleted == 1]
        if goal_type is not None:
            history_conditions.append(HealthGoal.goal_type == goal_type)
        history = db.execute(
            select(HealthGoal)
            .where(*history_conditions)
            .order_by(HealthGoal.created_at.desc(), HealthGoal.id.desc())
        ).scalars().all()
        items.extend(_goal_view(row, archived=True) for row in history)

    return {"items": items}


# ────────────────────────────── G-02 创建 ──────────────────────────────

def create_goal(db: Session, user_id: int, payload: Dict[str, Any],
                acknowledge: bool) -> Tuple[str, Dict[str, Any]]:
    """G-02：创建目标。

    返回 ``(kind, data)``，``kind`` ∈ ``{"written", "soft_warning"}``。
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    goal_type = _normalize_goal_type(payload.get("goal_type"))
    period = PERIOD_BY_TYPE[goal_type]

    # ① period_type：客户端传值必须与服务端强制值一致
    raw_period = payload.get("period_type")
    if raw_period is not None and str(raw_period).strip():
        if str(raw_period).strip() != period:
            errors.append(
                field_error("period_type", FieldErrorCode.INVALID_FORMAT, "周期类型与目标类型不一致")
            )

    # ② attr_1：仅 sport；sport 必填且取值受限
    attr_1 = _normalize_attr1(payload.get("attr_1"))
    if goal_type == "sport":
        if attr_1 is None:
            errors.append(field_error("attr_1", FieldErrorCode.REQUIRED, "计量方式不能为空"))
        elif attr_1 not in SPORT_ATTRS:
            errors.append(
                field_error("attr_1", FieldErrorCode.INVALID_FORMAT, "计量方式不在允许范围内")
            )
            attr_1 = None
    elif attr_1 is not None:
        errors.append(field_error("attr_1", FieldErrorCode.INVALID_FORMAT, "该目标类型不支持此字段"))
        attr_1 = None

    # ③ unit：服务端填充；客户端传值不一致 → 422
    expected_unit = unit_for(goal_type, attr_1)
    raw_unit = payload.get("unit")
    if raw_unit is not None and str(raw_unit).strip():
        if str(raw_unit).strip() != expected_unit:
            errors.append(field_error("unit", FieldErrorCode.INVALID_FORMAT, "单位与目标类型不一致"))

    # ④ 禁止字段（携带即非法）
    if goal_type != "weight":
        if payload.get("target_date") is not None:
            errors.append(
                field_error("target_date", FieldErrorCode.INVALID_FORMAT, "该目标类型不支持此字段")
            )
        if payload.get("start_weight_kg") is not None:
            errors.append(
                field_error("start_weight_kg", FieldErrorCode.INVALID_FORMAT, "该目标类型不支持此字段")
            )
        if payload.get("auto_start_weight"):
            errors.append(
                field_error("auto_start_weight", FieldErrorCode.INVALID_FORMAT, "该目标类型不支持此字段")
            )

    # ⑤ target_value
    target_value = _check_target_value(goal_type, attr_1, payload.get("target_value"),
                                       errors, warnings, "target_value")

    # ⑥ 日期
    today = now_local().date()
    start_date = _parse_date("start_date", payload.get("start_date")) or today
    target_date: Optional[date] = None
    if goal_type == "weight":
        target_date = _parse_date("target_date", payload.get("target_date"))
    if target_date is not None and start_date > target_date:
        errors.append(
            field_error("start_date", FieldErrorCode.INVALID_FORMAT, "开始日期不得晚于目标日期")
        )

    # ⑦ 体重目标：起始体重快照
    start_weight: Optional[Decimal] = None
    if goal_type == "weight":
        start_weight = _resolve_start_weight(db, user_id, payload, errors)

    # ⑧ 体重目标：target_value != start_weight_kg（相等则完成度无意义）
    if goal_type == "weight" and start_weight is not None and target_value is not None:
        if start_weight == target_value:
            errors.append(
                field_error("target_value", FieldErrorCode.INVALID_FORMAT,
                            "目标值与起始体重相同，无法计算完成度")
            )

    if errors:
        raise validation_error(errors)

    # ⑨ 同类型在用目标已存在 → 409（软删目标已释放唯一约束 → 可立即重建）
    if _active_exists(db, user_id, goal_type):
        raise ApiError(ErrorCode.GOAL_TYPE_EXISTS)

    # ⑩ 软提示：本次**不写入**（需 acknowledge_warnings=true 原样重发）
    if warnings and not acknowledge:
        return "soft_warning", soft_warning_payload(warnings)

    now = now_local()
    goal = HealthGoal(
        user_id=user_id,
        goal_type=goal_type,
        period_type=period,
        target_value=target_value,
        unit=expected_unit,
        attr_1=attr_1,
        start_weight_kg=start_weight,
        start_date=start_date,
        target_date=target_date,
        status=STATUS_ONGOING,
        is_deleted=0,
        deleted_marker=0,
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

    return "written", {"goal": _goal_view(goal), "warnings": list(warnings)}


def _check_target_value(goal_type: str, attr_1: Optional[str], raw: Any,
                        errors: List[Dict[str, Any]], warnings: List[Dict[str, Any]],
                        field: str) -> Optional[Decimal]:
    """``target_value`` 校验：必填 / 数字 / 精度 / 硬拦截 / 软提示。"""
    if raw is None:
        errors.append(field_error(field, FieldErrorCode.REQUIRED, "目标值不能为空"))
        return None
    num = _dec(raw)
    if num is None:
        errors.append(field_error(field, FieldErrorCode.INVALID_TYPE, "该字段必须为数字"))
        return None
    allowed = TARGET_DECIMALS.get(goal_type, 2)
    if _too_many_decimals(raw, allowed):
        errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "小数位数超出允许范围"))
        return num

    if goal_type == "sport":
        if attr_1 is None:
            return num                      # 计量方式已报错，跳过区间判定（避免重复报错）
        hard = HARD_SPORT_RANGE[attr_1]
        soft = SOFT_SPORT_RANGE[attr_1]
    else:
        hard = HARD_RANGE[goal_type]
        soft = SOFT_RANGE[goal_type]

    if not _check_range(raw, hard):
        errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "该数值不可能存在，请检查"))
        return num
    if not _check_range(raw, soft):
        warnings.append(out_of_range(field))
    return num


def _resolve_start_weight(db: Session, user_id: int, payload: Dict[str, Any],
                          errors: List[Dict[str, Any]]) -> Optional[Decimal]:
    """体重目标的起始体重快照（``auto_start_weight`` 取最近一条体重记录）。"""
    auto = bool(payload.get("auto_start_weight"))
    raw = payload.get("start_weight_kg")
    if auto:
        record = profile_service.latest_weight(db, user_id)
        if record is None or record.value_1 is None:
            errors.append(
                field_error("start_weight_kg", FieldErrorCode.INVALID_FORMAT,
                            "暂无体重记录，无法自动填充起始体重")
            )
            return None
        return Decimal(record.value_1)
    if raw is None:
        return None                          # 允许为空（完成度将为 null，不估算）
    num = _dec(raw)
    if num is None:
        errors.append(field_error("start_weight_kg", FieldErrorCode.INVALID_TYPE, "该字段必须为数字"))
        return None
    if _too_many_decimals(raw, 1):
        errors.append(
            field_error("start_weight_kg", FieldErrorCode.INVALID_FORMAT, "小数位数超出允许范围")
        )
    elif not _check_range(raw, START_WEIGHT_HARD):
        errors.append(
            field_error("start_weight_kg", FieldErrorCode.INVALID_FORMAT, "该数值超出可存储范围")
        )
    return num


# ────────────────────────────── G-03 修改 ──────────────────────────────

def patch_goal(db: Session, user_id: int, goal_id: int, payload: Dict[str, Any],
               acknowledge: bool) -> Tuple[str, Dict[str, Any]]:
    """G-03：局部更新（``goal_type`` / ``start_weight_kg`` 不允许修改）。"""
    goal = find_owned_goal(db, user_id, goal_id)
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if "goal_type" in payload:
        raise validation_error(
            [field_error("goal_type", FieldErrorCode.INVALID_FORMAT, "目标类型不允许修改")]
        )
    if "start_weight_kg" in payload:
        errors.append(
            field_error("start_weight_kg", FieldErrorCode.INVALID_FORMAT, "起始体重不允许修改")
        )

    goal_type = goal.goal_type

    # attr_1（仅 sport）
    attr_1 = goal.attr_1
    if "attr_1" in payload:
        if goal_type != "sport":
            errors.append(
                field_error("attr_1", FieldErrorCode.INVALID_FORMAT, "该目标类型不支持此字段")
            )
        else:
            candidate = _normalize_attr1(payload.get("attr_1"))
            if candidate not in SPORT_ATTRS:
                errors.append(
                    field_error("attr_1", FieldErrorCode.INVALID_FORMAT, "计量方式不在允许范围内")
                )
            else:
                attr_1 = candidate

    # unit（服务端填充；客户端传值不一致 → 422）
    expected_unit = unit_for(goal_type, attr_1)
    if "unit" in payload and payload.get("unit") is not None \
            and str(payload.get("unit")).strip():
        if str(payload["unit"]).strip() != expected_unit:
            errors.append(field_error("unit", FieldErrorCode.INVALID_FORMAT, "单位与目标类型不一致"))

    # target_date（仅 weight；显式 null = 清空）
    target_date = goal.target_date
    if "target_date" in payload:
        if goal_type != "weight":
            errors.append(
                field_error("target_date", FieldErrorCode.INVALID_FORMAT, "该目标类型不支持此字段")
            )
        else:
            target_date = _parse_date("target_date", payload.get("target_date"))

    # start_date
    start_date = goal.start_date
    if "start_date" in payload:
        parsed = _parse_date("start_date", payload.get("start_date"))
        start_date = parsed or goal.start_date
    if target_date is not None and start_date is not None and start_date > target_date:
        errors.append(
            field_error("start_date", FieldErrorCode.INVALID_FORMAT, "开始日期不得晚于目标日期")
        )

    # target_value
    target_value = goal.target_value
    if "target_value" in payload:
        target_value = _check_target_value(goal_type, attr_1, payload.get("target_value"),
                                           errors, warnings, "target_value")

    # 体重目标：目标值不得等于起始体重快照
    if goal_type == "weight" and goal.start_weight_kg is not None and target_value is not None:
        if Decimal(goal.start_weight_kg) == Decimal(target_value):
            errors.append(
                field_error("target_value", FieldErrorCode.INVALID_FORMAT,
                            "目标值与起始体重相同，无法计算完成度")
            )

    if errors:
        raise validation_error(errors)
    if warnings and not acknowledge:
        return "soft_warning", soft_warning_payload(warnings)

    now = now_local()
    goal.target_value = target_value
    goal.attr_1 = attr_1
    goal.unit = expected_unit
    goal.target_date = target_date
    goal.start_date = start_date
    goal.updated_at = now
    db.commit()
    db.refresh(goal)

    return "written", {"goal": _goal_view(goal), "warnings": list(warnings)}


# ────────────────────────────── G-04 / G-05 状态机 ──────────────────────────────

def pause_goal(db: Session, user_id: int, goal_id: int) -> Dict[str, Any]:
    """G-04：暂停（已暂停再调 → ``changed: false``，**不报错**）。"""
    goal = find_owned_goal(db, user_id, goal_id)
    if int(goal.status) == STATUS_PAUSED:
        return {"id": int(goal.id), "status": STATUS_PAUSED, "changed": False}
    goal.status = STATUS_PAUSED
    goal.updated_at = now_local()
    db.commit()
    return {"id": int(goal.id), "status": STATUS_PAUSED, "changed": True}


def resume_goal(db: Session, user_id: int, goal_id: int) -> Dict[str, Any]:
    """G-05：恢复（已进行中再调 → ``changed: false``）。

    恢复前必须判"同类型是否已有另一条在用目标" → 有则 ``409 GOAL_TYPE_EXISTS``，
    **不得产生两个在用目标**（唯一约束 ``uk_goal_user_type_active`` 口径）。
    """
    goal = find_owned_goal(db, user_id, goal_id)
    if int(goal.status) == STATUS_ONGOING:
        return {"id": int(goal.id), "status": STATUS_ONGOING, "changed": False}
    if _active_exists(db, user_id, goal.goal_type, exclude_id=int(goal.id)):
        raise ApiError(ErrorCode.GOAL_TYPE_EXISTS)
    goal.status = STATUS_ONGOING
    goal.updated_at = now_local()
    db.commit()
    return {"id": int(goal.id), "status": STATUS_ONGOING, "changed": True}


# ────────────────────────────── G-06 删除（软删） ──────────────────────────────

def delete_goal(db: Session, user_id: int, goal_id: int) -> Dict[str, Any]:
    """G-06：**软删**（三件事齐全；物理行保留；重复删除 → 404）。"""
    goal = find_owned_goal(db, user_id, goal_id)
    now = now_local()
    goal.is_deleted = 1
    goal.deleted_at = now
    goal.deleted_marker = int(goal.id)      # ★ 释放唯一约束，支持软删后重建
    goal.updated_at = now
    db.commit()
    return {"deleted_count": 1}


__all__ = [
    "GOAL_TYPES",
    "PERIOD_BY_TYPE",
    "UNIT_BY_TYPE",
    "SPORT_ATTRS",
    "STATUS_ONGOING",
    "STATUS_PAUSED",
    "STATUS_TEXT",
    "ARCHIVED_TEXT",
    "PERIOD_LABEL",
    "HARD_RANGE",
    "HARD_SPORT_RANGE",
    "SOFT_RANGE",
    "SOFT_SPORT_RANGE",
    "unit_for",
    "query_goal_type",
    "query_bool",
    "query_int",
    "find_owned_goal",
    "list_goals",
    "create_goal",
    "patch_goal",
    "pause_goal",
    "resume_goal",
    "delete_goal",
]
