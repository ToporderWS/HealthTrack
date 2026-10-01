# -*- coding: utf-8 -*-
"""健康记录指标规则表（8 类指标的必填矩阵、枚举字典与录入合理性区间）。

依据（**逐格对齐，不自行发明**）：
- 《S1-B 第二批 API 接口设计文档》§七 R-01「指标必填矩阵」、§3.14「统一健康值校验契约」
- 《S1-B 第二批 API 接口设计文档》§七 R-08「录入选项（枚举字典）」
- 《S0-产品规划报告》§7.2「各指标字段规划」的「输入校验区间」
- 《S0-产品规划报告》§7.5「数值合理性校验（F-023）的设计边界」的软提示 / 硬拦截区间

**红线（不得放宽）**：
- 本表的区间**只用于识别录入错误与不可能值**，**不是**任何医学参考区间；
- **不做**医学判断、**不给**建议、**不含**展示文案（中文文案由客户端映射）；
- 硬拦截**宁可漏拦不可误拦**（§7.5 五）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.core.errors import FieldErrorCode, field_error
from app.core.warnings import out_of_range

#: 允许的 8 类指标（受控枚举，§七 R-01）
METRIC_TYPES: Tuple[str, ...] = (
    "weight", "bp", "heart", "glucose", "sleep", "water", "sport", "mood",
)

#: 指标 → 单位（服务端自动填充；客户端传入不一致 → 422）
METRIC_UNIT: Dict[str, str] = {
    "weight": "kg",
    "bp": "mmHg",
    "heart": "bpm",
    "glucose": "mmol/L",
    "sleep": "score",
    "water": "ml",
    "sport": "min",
    "mood": "score",
}

#: R-08 静态枚举字典（服务端常量，**不落库**）
ENUMS: Dict[str, List[Dict[str, str]]] = {
    "bp_timing": [
        {"value": "morning", "label": "晨起"},
        {"value": "forenoon", "label": "上午"},
        {"value": "afternoon", "label": "午后"},
        {"value": "before_sleep", "label": "睡前"},
        {"value": "after_sport", "label": "运动后"},
        {"value": "after_med", "label": "服药后"},
    ],
    "heart_state": [
        {"value": "resting", "label": "静息"},
        {"value": "after_activity", "label": "活动后"},
        {"value": "during_sport", "label": "运动中"},
    ],
    "glucose_timing": [
        {"value": "fasting", "label": "空腹"},
        {"value": "after_meal_2h", "label": "餐后2h"},
        {"value": "before_sleep", "label": "睡前"},
        {"value": "random", "label": "随机"},
    ],
    "sport_type": [
        {"value": "running", "label": "跑步"},
        {"value": "walking", "label": "快走"},
        {"value": "cycling", "label": "骑行"},
        {"value": "swimming", "label": "游泳"},
        {"value": "strength", "label": "力量"},
        {"value": "ball", "label": "球类"},
        {"value": "yoga", "label": "瑜伽"},
        {"value": "other", "label": "其他"},
    ],
    "sport_intensity": [
        {"value": "low", "label": "低"},
        {"value": "mid", "label": "中"},
        {"value": "high", "label": "高"},
    ],
    "mood_tags": [
        {"value": "tired", "label": "疲惫"},
        {"value": "anxious", "label": "焦虑"},
        {"value": "relaxed", "label": "放松"},
        {"value": "focused", "label": "专注"},
        {"value": "low", "label": "低落"},
        {"value": "energetic", "label": "精神好"},
    ],
}

#: 快捷录入（F-020，服务端常量）
WATER_QUICK_ADD: Tuple[int, ...] = (200, 250, 500)

#: 枚举取值集合（用于校验）
_ENUM_VALUES: Dict[str, Tuple[str, ...]] = {
    k: tuple(item["value"] for item in v) for k, v in ENUMS.items()
}

#: 指标 → 允许携带的 ``attr_1`` 枚举名
ATTR1_ENUM: Dict[str, str] = {
    "bp": "bp_timing",
    "heart": "heart_state",
    "glucose": "glucose_timing",
    "sport": "sport_type",
}

#: 指标 → 允许携带的 ``attr_2`` 枚举名
ATTR2_ENUM: Dict[str, str] = {"sport": "sport_intensity"}

#: 数值字段名
NUMBER_FIELDS: Tuple[str, ...] = ("value_1", "value_2", "value_3")

#: 「区间」表示：``(下界, 下界是否含, 上界, 上界是否含)``；``None`` 表示无界
Range = Tuple[Optional[str], bool, Optional[str], bool]

#: 指标必填矩阵（与 S1-B §七 R-01 表格逐格一致）
#: ``required`` 必填；``forbidden`` 禁止携带（携带 → 422）
MATRIX: Dict[str, Dict[str, Sequence[str]]] = {
    "weight": {
        "required": ("value_1",),
        "forbidden": ("value_2", "value_3", "attr_1", "attr_2", "time_start", "tags"),
    },
    "bp": {
        "required": ("value_1", "value_2"),
        "forbidden": ("attr_2", "time_start", "tags"),
    },
    "heart": {
        "required": ("value_1",),
        "forbidden": ("value_2", "value_3", "attr_2", "time_start", "tags"),
    },
    "glucose": {
        "required": ("value_1", "attr_1"),
        "forbidden": ("value_2", "value_3", "attr_2", "time_start", "tags"),
    },
    "sleep": {
        "required": ("time_start", "recorded_at"),
        "forbidden": ("value_2", "value_3", "attr_1", "attr_2", "tags"),
    },
    "water": {
        "required": ("value_1",),
        "forbidden": ("value_2", "value_3", "attr_1", "attr_2", "time_start", "tags"),
    },
    "sport": {
        "required": ("value_1", "attr_1"),
        "forbidden": ("value_3", "time_start", "tags"),
    },
    "mood": {
        # 注：S1-B 矩阵中 mood 的 value_1 未列入「禁止」列，故按必填处理
        "required": ("value_1",),
        "forbidden": ("value_2", "value_3", "attr_1", "attr_2", "time_start"),
    },
}

#: 字段 → 允许的最大小数位
DECIMALS: Dict[str, Dict[str, int]] = {
    "weight": {"value_1": 1},
    "bp": {"value_1": 0, "value_2": 0, "value_3": 0},
    "heart": {"value_1": 0},
    "glucose": {"value_1": 1},
    "sleep": {"value_1": 0},
    "water": {"value_1": 0},
    "sport": {"value_1": 0, "value_2": 2},
    "mood": {"value_1": 0},
}

#: 录入合理性区间（超出 → **软提示**；来源 S0 §7.2 / §流程 4）
SOFT_RANGE: Dict[str, Dict[str, Range]] = {
    "weight": {"value_1": ("20", True, "300", True)},
    "bp": {
        "value_1": ("60", True, "250", True),
        "value_2": ("30", True, "150", True),
        "value_3": ("30", True, "220", True),
    },
    "heart": {"value_1": ("30", True, "220", True)},
    "glucose": {"value_1": ("1.0", True, "35.0", True)},
    "water": {"value_1": ("50", True, "2000", True)},
    "sport": {"value_1": ("1", True, "600", True), "value_2": ("0", True, "5000", True)},
}

#: 明显不可能值区间（超出 → **硬拦截**；来源 S0 §流程 4）
HARD_RANGE: Dict[str, Dict[str, Range]] = {
    "weight": {"value_1": ("10", True, "500", True)},
    "bp": {
        "value_1": ("30", True, "400", True),
        "value_2": ("20", True, "300", True),
        "value_3": ("20", True, "300", True),
    },
    "heart": {"value_1": ("20", True, "300", True)},
    "glucose": {"value_1": ("0", False, "50", True)},
    "water": {"value_1": ("0", False, "5000", True)},
    "sport": {"value_1": ("0", False, "1440", True), "value_2": ("0", True, None, False)},
}

#: 定义域（枚举式数值，超出即非法 → 硬拦截；**不做**医学判断）
DOMAIN_RANGE: Dict[str, Dict[str, Range]] = {
    "sleep": {"value_1": ("1", True, "5", True)},   # 睡眠质量 1–5
    "mood": {"value_1": ("1", True, "5", True)},     # 心情评分 1–5
}

#: 睡眠时长区间（由 ``time_start`` 与 ``recorded_at`` 推导，不落库）
SLEEP_DURATION_SOFT_HOURS: Range = ("1", True, "16", True)
SLEEP_DURATION_HARD_HOURS: Range = ("0", False, "24", True)


def _dec(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


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


def _range_text(rng: Range) -> str:
    lo, lo_inc, hi, hi_inc = rng
    left = ("[" if lo_inc else "(") + str(lo)
    right = str(hi) + ("]" if hi_inc else ")")
    return f"{left}, {right}"


def decimals_of(metric_type: str, field: str) -> Optional[int]:
    return DECIMALS.get(metric_type, {}).get(field)


def _too_many_decimals(value: Any, allowed: int) -> bool:
    """小数位是否超出业务精度。

    ★ 先 ``normalize()`` 去除**无意义的尾随零**：
    ``health_record.value_1`` 为 ``Numeric(10,2)``，DB 回读形如 ``Decimal('72.50')``，
    对**未改动字段**复用时不得被判为「2 位小数」而误拦截（R-04 局部更新）。
    """
    num = _dec(value)
    if num is None:
        return False
    num = num.normalize()
    if num == num.to_integral_value():
        return False
    if allowed <= 0:
        return True
    return -num.as_tuple().exponent > allowed


def normalize_attr(metric_type: str, attr_1: Any, attr_2: Any) -> Tuple[Optional[str], Optional[str]]:
    """``attr_1`` / ``attr_2`` 归一化（``""`` → ``None``）。"""
    a1 = attr_1.strip() if isinstance(attr_1, str) else attr_1
    a2 = attr_2.strip() if isinstance(attr_2, str) else attr_2
    return (a1 or None), (a2 or None)


def normalize_tags(raw: Any) -> List[str]:
    """标签归一化：保序去重、去空白、去空串。"""
    if not raw:
        return []
    seen: Set[str] = set()
    out: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def validate_record(
    metric_type: str,
    values: Dict[str, Any],
    *,
    present: Optional[Set[str]] = None,
    forbid_check: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """校验一条记录（新建或编辑后的**有效字段值**）。

    参数
    ----
    metric_type : 指标类型（必须已在 ``METRIC_TYPES`` 内）
    values      : **有效值**字典（编辑场景 = 原值 + 本次改动）
    present     : 本次请求**显式携带**的字段名集合（用于「禁止字段」判定）
    forbid_check: 是否执行「禁止字段」判定（编辑场景同样需要）

    返回
    ----
    ``(errors, warnings)``
    - ``errors`` 非空 → ``422 VALIDATION_FAILED``（**不写入**）
    - ``warnings`` 非空且未确认 → ``200 SOFT_WARNING``（**本次不写入**）
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    rules = MATRIX.get(metric_type)
    if rules is None:
        return [field_error("metric_type", FieldErrorCode.INVALID_FORMAT, "指标类型不在允许范围内")], []

    present = set(present or ())
    hard = HARD_RANGE.get(metric_type, {})
    soft = SOFT_RANGE.get(metric_type, {})
    domain = DOMAIN_RANGE.get(metric_type, {})
    dec = DECIMALS.get(metric_type, {})

    # ① 禁止字段（携带即非法）
    if forbid_check:
        for field in rules.get("forbidden", ()):  # type: ignore[arg-type]
            if field in present:
                errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "该指标不支持此字段"))

    # ② 必填
    for field in rules.get("required", ()):  # type: ignore[arg-type]
        if values.get(field) is None:
            errors.append(field_error(field, FieldErrorCode.REQUIRED, "该字段不能为空"))

    # ③ 数值：类型 / 精度 / 定义域 / 不可能值（硬拦截） / 常见范围（软提示）
    for field in NUMBER_FIELDS:
        raw = values.get(field)
        if raw is None:
            continue
        num = _dec(raw)
        if num is None:
            errors.append(field_error(field, FieldErrorCode.INVALID_TYPE, "该字段必须为数字"))
            continue
        if field in dec and _too_many_decimals(raw, dec[field]):
            errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "小数位数超出允许范围"))
            continue
        if field in domain and not _check_range(raw, domain[field]):
            errors.append(
                field_error(field, FieldErrorCode.INVALID_FORMAT,
                            f"取值须在 {_range_text(domain[field])} 内")
            )
            continue
        if field in hard and not _check_range(raw, hard[field]):
            errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "该数值不可能存在，请检查"))
            continue
        if field in soft and not _check_range(raw, soft[field]):
            warnings.append(out_of_range(field))

    # ④ 字段间逻辑矛盾（硬拦截）
    if metric_type == "bp":
        systolic, diastolic = _dec(values.get("value_1")), _dec(values.get("value_2"))
        if systolic is not None and diastolic is not None and diastolic >= systolic:
            errors.append(
                field_error("value_2", FieldErrorCode.INVALID_FORMAT, "舒张压不能大于等于收缩压")
            )

    if metric_type == "sleep":
        start, end = values.get("time_start"), values.get("recorded_at")
        if start is not None and end is not None and start >= end:
            errors.append(
                field_error("time_start", FieldErrorCode.INVALID_FORMAT, "入睡时间须早于起床时间")
            )
        else:
            duration_h = sleep_duration_hours(values)
            if duration_h is not None:
                if not _check_range(duration_h, SLEEP_DURATION_HARD_HOURS):
                    errors.append(
                        field_error("recorded_at", FieldErrorCode.INVALID_FORMAT, "该时长不可能存在，请检查")
                    )
                elif not _check_range(duration_h, SLEEP_DURATION_SOFT_HOURS):
                    warnings.append(out_of_range("recorded_at"))

    # ⑤ 枚举
    a1_enum = ATTR1_ENUM.get(metric_type)
    a1 = values.get("attr_1")
    if a1_enum and a1 is not None and a1 not in _ENUM_VALUES[a1_enum]:
        errors.append(field_error("attr_1", FieldErrorCode.INVALID_FORMAT, "该选项不在允许范围内"))

    a2_enum = ATTR2_ENUM.get(metric_type)
    a2 = values.get("attr_2")
    if a2_enum and a2 is not None and a2 not in _ENUM_VALUES[a2_enum]:
        errors.append(field_error("attr_2", FieldErrorCode.INVALID_FORMAT, "该选项不在允许范围内"))

    if metric_type != "mood" and values.get("tags"):
        errors.append(field_error("tags", FieldErrorCode.INVALID_FORMAT, "该指标不支持标签"))

    note = values.get("note")
    if note is not None and len(str(note)) > 200:
        errors.append(field_error("note", FieldErrorCode.INVALID_FORMAT, "备注长度超出限制"))

    return errors, warnings


def validate_tags(raw_tags: Any) -> Optional[str]:
    """标签枚举校验；返回错误说明（``None`` = 合法）。"""
    allowed = set(_ENUM_VALUES["mood_tags"])
    tags = normalize_tags(raw_tags)
    if len(tags) > 6:
        return "标签数量超出限制"
    for tag in tags:
        if tag not in allowed:
            return "标签取值不在允许范围内"
    return None


def sleep_duration_hours(values: Dict[str, Any]) -> Optional[Decimal]:
    """睡眠时长（小时，1 位小数）——**派生值，不落库**。"""
    start, end = values.get("time_start"), values.get("recorded_at")
    if start is None or end is None:
        return None
    try:
        seconds = (end - start).total_seconds()
    except (TypeError, AttributeError):
        return None
    return (Decimal(int(seconds)) / Decimal(3600)).quantize(Decimal("0.1"))


def options_payload() -> Dict[str, Any]:
    """R-08 响应载荷（纯常量，**不访问数据库**）。"""
    return {
        "metric_types": [
            {"value": key, "label": item["label"], "unit": METRIC_UNIT[key]}
            for key, item in _METRIC_LABELS.items()
        ],
        "enums": {k: [dict(x) for x in v] for k, v in ENUMS.items()},
        "water_quick_add": list(WATER_QUICK_ADD),
    }


#: 指标中文标签（**中性**，仅用于选项字典回显，不含任何评价性表述）
_METRIC_LABELS: Dict[str, Dict[str, str]] = {
    "weight": {"label": "体重"},
    "bp": {"label": "血压"},
    "heart": {"label": "心率"},
    "glucose": {"label": "血糖"},
    "sleep": {"label": "睡眠"},
    "water": {"label": "饮水"},
    "sport": {"label": "运动"},
    "mood": {"label": "心情"},
}


__all__ = [
    "METRIC_TYPES",
    "METRIC_UNIT",
    "ENUMS",
    "WATER_QUICK_ADD",
    "MATRIX",
    "SOFT_RANGE",
    "HARD_RANGE",
    "DOMAIN_RANGE",
    "validate_record",
    "validate_tags",
    "normalize_tags",
    "normalize_attr",
    "decimals_of",
    "sleep_duration_hours",
    "options_payload",
]
