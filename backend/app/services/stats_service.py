# -*- coding: utf-8 -*-
"""首页 / 统计 / 趋势聚合服务（本批实现 **S-01 ~ S-03**）。

依据（**逐项对齐，不自行发明字段**）：
- 《S1-B 第二批 API 接口设计文档》§九「首页 / 统计 / 趋势 API（模块 S，3 个）」
  → S-01 首页概览 / S-02 趋势数据 / S-03 统计摘要（成功响应示例 + 响应结构表 + 差异字段表）
- 《S0-产品规划报告》§9.1 时间窗口、§9.2 图表与统计指标清单、§9.3 统计摘要卡、§9.4 计算口径
- 《S1-D 技术方案最终冻结》D-4（单一时区 / naive 本地时间）、D-5（窗口半开区间反推）
- 《S2 第五批-开工前实施方案》§四 ~ §九（**仅补充实现细节**，不新增冻结字段）

**统一口径**：
- ``user_id`` 只来自 Access Token；**每次查询显式带 ``user_id``**；
- **每次聚合显式带 ``is_deleted=0``**（S1-B 13.1「聚合隔离」，评审必查项）；
- 时间一律半开区间 ``[start, end)``，**不使用 BETWEEN**；跨天睡眠按 ``recorded_at``（起床日）归属；
- **缺失日期不补零、不插值**；
- 窗口 ``start = end − (window − 1)``（T-1 默认，约束"点数 ≤ window"优先）；
- ``end`` **允许未来日期**（T-4：仅格式校验；未来窗口无记录 → 空数据，有记录 → 正常参与统计，**不人为清空**）。

**红线**：只输出**数值 / 日期 / 条数 / 极值 / 变化量**事实；
**不返回**任何医学判断、评价、正常范围、建议或红绿语义（红线约束：非医学输出，仅陈述事实）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.security import now_local
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.record_tag import RecordTag
from app.services import goal_progress, metric_rules, profile_service

#: 允许的窗口天数（其他值 → ``400 INVALID_PARAM``）
WINDOW_DAYS: Tuple[int, ...] = (7, 30, 90)
DEFAULT_WINDOW = 7

#: 指标 → 图表类型（S1-B §九 S-02 响应结构表）
CHART: Dict[str, str] = {
    "weight": "line",
    "bp": "line",
    "heart": "line",
    "glucose": "line",
    "sleep": "bar",
    "water": "bar",
    "sport": "bar",
    "mood": "line",
}

#: S-01 ``goals[]`` 每项**仅**输出的 8 个字段（冻结示例字段集，**不增不减**）
GOAL_FIELDS: Tuple[str, ...] = (
    "goal_id", "goal_type", "target_value", "current_value",
    "unit", "progress_percent", "is_reached", "remaining_text",
)

#: S-01 ``reminder_fallback`` **固定常量**（S1-B §九 G-7 冻结占位语义）
REMINDER_FALLBACK: Dict[str, str] = {
    "source": "local",
    "note": "N/A（提醒兜底计数由客户端本地计算，服务端不提供）",
}

#: 仅这两个指标输出 ``target_line``
TARGET_LINE_METRICS: Tuple[str, ...] = ("weight", "water")


# ════════════════════════════════════════════════════════════════════
# 数值 / 时间工具
# ════════════════════════════════════════════════════════════════════
def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _num(value: Optional[Any]) -> Optional[Any]:
    """数值输出归一：整数值 → ``int``，否则 ``float``（复用既有 ``_num`` 风格）。"""
    if value is None:
        return None
    dec = _dec(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _hours1(value: Optional[Any]) -> Optional[float]:
    """时长输出：恒 **1 位小数** 的 ``float``（``duration_hours`` 冻结口径）。"""
    if value is None:
        return None
    return float(_dec(value).quantize(Decimal("0.1")))


def _mean(values: Iterable[Optional[Any]]) -> Optional[Decimal]:
    """算术平均（**忽略 None**；全空 → ``None``）。"""
    nums = [_dec(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums, Decimal(0)) / Decimal(len(nums))


def _pct(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def _day_bounds(day: date) -> Tuple[datetime, datetime]:
    """半开区间 ``[当日 00:00:00, 次日 00:00:00)``。"""
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def _week_start(day: date) -> date:
    """本周起点（**周一**）。"""
    return day - timedelta(days=day.weekday())


def _window_weeks(start: date, end: date) -> int:
    """窗口 ``[start, end]`` 覆盖的不重复周一起点数（与是否有记录无关）。"""
    weeks = set()
    cursor = start
    while cursor <= end:
        weeks.add(_week_start(cursor))
        cursor += timedelta(days=1)
    return max(len(weeks), 1)


# ════════════════════════════════════════════════════════════════════
# 查询参数解析（非法 → ``400 INVALID_PARAM``，**不新增错误码**）
# ════════════════════════════════════════════════════════════════════
def _clean(args: Dict[str, Any], name: str) -> Optional[str]:
    raw = args.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_tz(args: Dict[str, Any]) -> Optional[int]:
    """S-01 ``tz_offset_minutes``：**仅校验**（T-2 默认不偏移）。"""
    text = _clean(args, "tz_offset_minutes")
    if text is None:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError(ErrorCode.INVALID_PARAM)


def _parse_metric(args: Dict[str, Any]) -> str:
    """``metric_type``：必填且必须为 8 类之一。"""
    value = _clean(args, "metric_type")
    if value is None or value not in metric_rules.METRIC_TYPES:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return value


def _parse_window(args: Dict[str, Any]) -> int:
    """``window``：7 / 30 / 90，默认 7。"""
    text = _clean(args, "window")
    if text is None:
        return DEFAULT_WINDOW
    try:
        days = int(text)
    except (TypeError, ValueError):
        raise ApiError(ErrorCode.INVALID_PARAM)
    if days not in WINDOW_DAYS:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return days


def _parse_end(args: Dict[str, Any], today: date) -> date:
    """``end``：默认当前日；**仅格式校验**（允许未来日期，T-4）。

    格式**严格**为 ``YYYY-MM-DD``（零填充、10 字符）—— ``2026-9-1`` / ``2026/09/01``
    / ``abc`` / ``2026-13-01`` 一律 ``400 INVALID_PARAM``；**不**新增"禁止未来日期"规则。
    """
    text = _clean(args, "end")
    if text is None:
        return today
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ApiError(ErrorCode.INVALID_PARAM)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(ErrorCode.INVALID_PARAM)


def _parse_group_by(args: Dict[str, Any], metric_type: str) -> Optional[str]:
    """``group_by``：**仅** ``glucose``+``timing``、**仅** ``mood``+``tag`` 合法。"""
    value = _clean(args, "group_by")
    if value is None:
        return None
    if metric_type == "glucose" and value == "timing":
        return value
    if metric_type == "mood" and value == "tag":
        return value
    raise ApiError(ErrorCode.INVALID_PARAM)


def _resolve_window(args: Dict[str, Any], today: date) -> Tuple[int, date, date]:
    days = _parse_window(args)
    end = _parse_end(args, today)
    start = end - timedelta(days=days - 1)
    return days, start, end


def _window_payload(days: int, start: date, end: date) -> Dict[str, Any]:
    return {"days": days, "start": start.isoformat(), "end": end.isoformat()}


# ════════════════════════════════════════════════════════════════════
# 取数（**一律带 user_id + is_deleted=0 + 半开区间**）
# ════════════════════════════════════════════════════════════════════
def _fetch_records(db: Session, user_id: int, metric_type: str,
                   start: Optional[datetime] = None,
                   end: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """按 ``recorded_at ASC, id ASC`` 取窗口内有效记录（显式排序，避免同秒不确定）。"""
    stmt = select(
        HealthRecord.id,
        HealthRecord.recorded_at,
        HealthRecord.value_1,
        HealthRecord.value_2,
        HealthRecord.attr_1,
        HealthRecord.time_start,
    ).where(
        HealthRecord.user_id == user_id,
        HealthRecord.metric_type == metric_type,
        HealthRecord.is_deleted == 0,
    )
    if start is not None:
        stmt = stmt.where(HealthRecord.recorded_at >= start)
    if end is not None:
        stmt = stmt.where(HealthRecord.recorded_at < end)
    stmt = stmt.order_by(HealthRecord.recorded_at.asc(), HealthRecord.id.asc())
    return [dict(row._mapping) for row in db.execute(stmt).all()]


def _group_by_day(rows: List[Dict[str, Any]]) -> Dict[date, List[Dict[str, Any]]]:
    days: Dict[date, List[Dict[str, Any]]] = {}
    for row in rows:
        days.setdefault(row["recorded_at"].date(), []).append(row)
    return days


def _sleep_hours(row: Dict[str, Any]) -> Decimal:
    """单条睡眠记录派生长度（小时）；缺失 → ``0``（**不估算**）。"""
    hours = metric_rules.sleep_duration_hours(
        {"time_start": row["time_start"], "recorded_at": row["recorded_at"]}
    )
    return _dec(hours) if hours is not None else Decimal(0)


def _day_values(metric_type: str,
                days_map: Dict[date, List[Dict[str, Any]]]) -> Dict[date, Decimal]:
    """各指标的**日值**（S-02 / S-03 共用；缺失日期不出现）。

    ============================  ==================================================
    ``weight``                    当日**最后一次**记录的 ``value_1``
    ``bp``                        当日 ``value_1``（收缩压）算术平均
    ``heart`` / ``glucose`` / ``mood``  当日 ``value_1`` 算术平均
    ``sleep``                     当日**累计**睡眠时长（小时）
    ``water`` / ``sport``         当日 ``value_1`` **累计**
    ============================  ==================================================
    """
    out: Dict[date, Decimal] = {}
    for day, rows in days_map.items():
        if metric_type == "weight":
            out[day] = _dec(rows[-1]["value_1"])
        elif metric_type == "bp":
            out[day] = _mean([r["value_1"] for r in rows])  # type: ignore[assignment]
        elif metric_type in ("heart", "glucose", "mood"):
            out[day] = _mean([r["value_1"] for r in rows])  # type: ignore[assignment]
        elif metric_type == "sleep":
            out[day] = sum((_sleep_hours(r) for r in rows), Decimal(0))
        else:  # water / sport
            out[day] = sum((_dec(r["value_1"]) for r in rows), Decimal(0))
    return out


def _active_goal(db: Session, user_id: int, goal_type: str) -> Optional[HealthGoal]:
    """本人在用的同类目标（``is_deleted=0``；唯一键保证至多 1 条）。"""
    return db.execute(
        select(HealthGoal)
        .where(
            HealthGoal.user_id == user_id,
            HealthGoal.goal_type == goal_type,
            HealthGoal.is_deleted == 0,
        )
        .order_by(HealthGoal.id.asc())
    ).scalars().first()


def _target_line(db: Session, user_id: int, goal_type: str) -> Optional[Dict[str, Any]]:
    goal = _active_goal(db, user_id, goal_type)
    if goal is None:
        return None
    return {
        "value": _num(goal.target_value),
        "unit": goal.unit,
        "source": "health_goal",
        "goal_id": int(goal.id),
    }


def _tag_counts(db: Session, record_ids: List[int]) -> Dict[str, int]:
    """``record_tag`` 标签出现次数（``is_deleted=0``）。"""
    if not record_ids:
        return {}
    rows = db.execute(
        select(RecordTag.tag_value).where(
            RecordTag.record_id.in_(record_ids),
            RecordTag.is_deleted == 0,
        )
    ).all()
    counts: Dict[str, int] = {}
    for (tag_value,) in rows:
        counts[tag_value] = counts.get(tag_value, 0) + 1
    return counts


# ════════════════════════════════════════════════════════════════════
# S-01 首页概览
# ════════════════════════════════════════════════════════════════════
def home_overview(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """S-01：首页概览（今日概览 + 目标环 + 最近 10 条 + 提醒兜底占位）。

    - 今日 = ``[今日 00:00:00, 明日 00:00:00)``（半开区间）；
    - ``goals[]`` **只读复用 G-07**（``goal_progress.list_progress``），仅取 8 个字段；
    - ``recent_records`` 固定 **10 条**，``recorded_at DESC, id DESC``。
    """
    _parse_tz(args)
    today = now_local().date()
    start_dt, end_dt = _day_bounds(today)

    today_rows = db.execute(
        select(HealthRecord.metric_type).where(
            HealthRecord.user_id == user_id,
            HealthRecord.is_deleted == 0,
            HealthRecord.recorded_at >= start_dt,
            HealthRecord.recorded_at < end_dt,
        )
    ).all()
    recorded = {row[0] for row in today_rows}
    # 按 METRIC_TYPES 固定顺序去重输出（确定性排序）
    metric_types_recorded = [m for m in metric_rules.METRIC_TYPES if m in recorded]

    progress = goal_progress.list_progress(db, user_id, {})
    goals = [
        {field: item.get(field) for field in GOAL_FIELDS}
        for item in progress.get("items", [])
    ]

    recent_rows = db.execute(
        select(HealthRecord)
        .where(HealthRecord.user_id == user_id, HealthRecord.is_deleted == 0)
        .order_by(HealthRecord.recorded_at.desc(), HealthRecord.id.desc())
        .limit(10)
    ).scalars().all()
    recent_records: List[Dict[str, Any]] = []
    for record in recent_rows:
        tags = [
            tag
            for (tag,) in db.execute(
                select(RecordTag.tag_value)
                .where(RecordTag.record_id == record.id, RecordTag.is_deleted == 0)
                .order_by(RecordTag.id.asc())
            ).all()
        ]
        recent_records.append({
            "id": int(record.id),
            "metric_type": record.metric_type,
            "value_1": _num(record.value_1),
            "unit": record.unit,
            "recorded_at": record.recorded_at.strftime("%Y-%m-%d %H:%M:%S"),
            "time_start": (
                record.time_start.strftime("%Y-%m-%d %H:%M:%S")
                if record.time_start is not None else None
            ),
            "note": record.note,
            "tags": tags,
        })

    return {
        "date": today.isoformat(),
        "today": {
            "record_count": len(today_rows),
            "metric_types_recorded": metric_types_recorded,
        },
        "goals": goals,
        "recent_records": recent_records,
        "reminder_fallback": dict(REMINDER_FALLBACK),
    }


# ════════════════════════════════════════════════════════════════════
# S-02 趋势数据
# ════════════════════════════════════════════════════════════════════
def _trend_points(metric_type: str,
                  days_map: Dict[date, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    for day in sorted(days_map):
        rows = days_map[day]
        iso = day.isoformat()
        if metric_type == "weight":
            points.append({"date": iso, "value": _num(rows[-1]["value_1"])})
        elif metric_type == "bp":
            points.append({
                "date": iso,
                "systolic": _num(_mean([r["value_1"] for r in rows])),
                "diastolic": _num(_mean([r["value_2"] for r in rows])),
            })
        elif metric_type in ("heart", "glucose", "mood"):
            points.append({"date": iso, "value": _num(_mean([r["value_1"] for r in rows]))})
        elif metric_type == "sleep":
            points.append({
                "date": iso,
                "duration_hours": _hours1(sum((_sleep_hours(r) for r in rows), Decimal(0))),
                "quality": _num(_mean([r["value_1"] for r in rows])),
            })
        elif metric_type == "water":
            points.append({
                "date": iso,
                "total_ml": _num(sum((_dec(r["value_1"]) for r in rows), Decimal(0))),
            })
        else:  # sport
            points.append({
                "date": iso,
                "minutes": _num(sum((_dec(r["value_1"]) for r in rows), Decimal(0))),
                "count": len(rows),
            })
    return points


def _glucose_groups(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``glucose`` + ``group_by=timing``：按 ``attr_1`` 分组均值（枚举固定序）。"""
    groups: List[Dict[str, Any]] = []
    for item in metric_rules.ENUMS["glucose_timing"]:
        value = _mean([r["value_1"] for r in rows if r["attr_1"] == item["value"]])
        if value is not None:
            groups.append({"timing": item["value"], "value": _num(value)})
    return groups


def _sport_weekly(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``sport`` 周汇总 ``[{week_start, minutes, count}]``（仅实际有记录的周）。"""
    weeks: Dict[date, List[Dict[str, Any]]] = {}
    for row in rows:
        weeks.setdefault(_week_start(row["recorded_at"].date()), []).append(row)
    return [
        {
            "week_start": week.isoformat(),
            "minutes": _num(sum((_dec(r["value_1"]) for r in items), Decimal(0))),
            "count": len(items),
        }
        for week, items in sorted(weeks.items())
    ]


def _mood_distribution(db: Session, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``mood`` 标签分布 ``[{tag, count}]``（``mood_tags`` 固定序，仅出现 ≥1）。"""
    counts = _tag_counts(db, [int(r["id"]) for r in rows])
    return [
        {"tag": item["value"], "count": counts[item["value"]]}
        for item in metric_rules.ENUMS["mood_tags"]
        if counts.get(item["value"])
    ]


def trend(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """S-02：趋势数据（不分页，点数 ≤ 90；缺失日期不补零）。"""
    metric_type = _parse_metric(args)
    group_by = _parse_group_by(args, metric_type)
    today = now_local().date()
    days, start, end = _resolve_window(args, today)
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.min) + timedelta(days=1)

    rows = _fetch_records(db, user_id, metric_type, start_dt, end_dt)
    days_map = _group_by_day(rows)
    points = _trend_points(metric_type, days_map)

    data: Dict[str, Any] = {
        "metric_type": metric_type,
        "unit": metric_rules.METRIC_UNIT[metric_type],
        "window": _window_payload(days, start, end),
        "chart": CHART[metric_type],
        "insufficient_data": len(points) < 2,
        "points": points,
    }
    if metric_type in TARGET_LINE_METRICS:
        data["target_line"] = _target_line(db, user_id, metric_type)
    if metric_type == "glucose" and group_by == "timing":
        data["groups"] = _glucose_groups(rows)
    if metric_type == "sport":
        data["weekly"] = _sport_weekly(rows)
    if metric_type == "mood":
        data["tag_distribution"] = _mood_distribution(db, rows)
    return data


# ════════════════════════════════════════════════════════════════════
# S-03 统计摘要
# ════════════════════════════════════════════════════════════════════
def _extreme(days_sorted: List[date], values: Dict[date, Decimal],
             want_max: bool) -> Optional[Dict[str, Any]]:
    """极值 + **发生日期**（并列取**最早**出现日）。"""
    if not days_sorted:
        return None
    target = (max if want_max else min)(values[d] for d in days_sorted)
    day = next(d for d in days_sorted if values[d] == target)
    return {"value": _num(target), "date": day.isoformat()}


def _reached_rate(metric_type: str, day_values: Dict[date, Decimal],
                  goal: Optional[HealthGoal]) -> Optional[float]:
    """达标率 = 达标日数 ÷ 有记录天数 × 100（1 位小数）。

    - **无同类目标 → ``None``**；**有记录天数 = 0 → ``None``**（不除零）；
    - ``weight`` 目标按 G-07 冻结口径**恒 ``None``**（``rate`` 仅 ``daily``/``weekly`` 有）；
    - ``weekly`` 目标按"当日所属周"的周累计判定（与 G-07 ``_rate`` 同口径）。
    """
    if goal is None or metric_type == "weight" or not day_values:
        return None
    target = _dec(goal.target_value)
    recorded = sorted(day_values)
    if goal.period_type == "weekly":
        week_totals: Dict[date, Decimal] = {}
        for day, value in day_values.items():
            key = _week_start(day)
            week_totals[key] = week_totals.get(key, Decimal(0)) + value
        reached = [d for d in recorded if week_totals[_week_start(d)] >= target]
    else:
        reached = [d for d in recorded if day_values[d] >= target]
    return _pct(len(reached), len(recorded))


def _longest_streak(day_values: Dict[date, Decimal], target: Decimal) -> int:
    """最长**连续**达标天数（中间缺记录即中断，不补零）。"""
    best = run = 0
    previous: Optional[date] = None
    for day in sorted(day_values):
        if day_values[day] >= target:
            run = run + 1 if previous is not None and (day - previous).days == 1 else 1
            best = max(best, run)
            previous = day
        else:
            run = 0
            previous = None
    return best


def _summary_extras(db: Session, user_id: int, metric_type: str,
                    rows: List[Dict[str, Any]], days_map: Dict[date, List[Dict[str, Any]]],
                    day_values: Dict[date, Decimal], goal: Optional[HealthGoal],
                    start: date, end: date) -> Dict[str, Any]:
    """各指标差异字段（S1-B §九 S-03 差异字段表，**仅补充元素形态**）。"""
    ordered = sorted(day_values)
    if metric_type == "weight":
        distance: Optional[Any] = None
        if goal is not None:
            latest = profile_service.latest_weight(db, user_id)
            if latest is not None and latest.value_1 is not None:
                distance = _num(_dec(latest.value_1) - _dec(goal.target_value))
        return {"distance_to_target": distance}

    if metric_type == "bp":
        return {
            "average_systolic": _num(_mean([r["value_1"] for r in rows])),
            "average_diastolic": _num(_mean([r["value_2"] for r in rows])),
            "measure_count": len(rows),
        }

    if metric_type == "heart":
        value = _mean([r["value_1"] for r in rows if r["attr_1"] == "resting"])
        return {"resting_average": _num(value)}

    if metric_type == "glucose":
        return {
            "average_fasting": _num(_mean(
                [r["value_1"] for r in rows if r["attr_1"] == "fasting"])),
            "average_after_meal": _num(_mean(
                [r["value_1"] for r in rows if r["attr_1"] == "after_meal_2h"])),
            "measure_count": len(rows),
        }

    if metric_type == "sleep":
        durations = [day_values[d] for d in ordered]
        return {
            "average_duration_hours": _hours1(_mean(durations)),
            "longest": _extreme(ordered, day_values, True),
            "shortest": _extreme(ordered, day_values, False),
            "average_quality": _num(_mean([r["value_1"] for r in rows])),
        }

    if metric_type == "water":
        reached_days = ([d for d in ordered if day_values[d] >= _dec(goal.target_value)]
                        if goal is not None else [])
        return {
            "daily_average_ml": _num(_mean([day_values[d] for d in ordered])),
            "reached_day_count": len(reached_days),
            "longest_streak_days": (
                _longest_streak(day_values, _dec(goal.target_value)) if goal is not None else 0
            ),
        }

    if metric_type == "sport":
        total = sum((day_values[d] for d in ordered), Decimal(0))
        weeks = _window_weeks(start, end)
        reached_weeks = 0
        if goal is not None:
            target = _dec(goal.target_value)
            week_totals: Dict[date, Decimal] = {}
            for day, value in day_values.items():
                key = _week_start(day)
                week_totals[key] = week_totals.get(key, Decimal(0)) + value
            reached_weeks = sum(1 for v in week_totals.values() if v >= target)
        return {
            "total_minutes": _num(total),
            "daily_average_minutes": _num(_mean([day_values[d] for d in ordered])),
            "session_count": len(rows),
            "reached_week_count": reached_weeks,
            "weekly_average_minutes": _num(total / Decimal(weeks)) if weeks else 0,
        }

    # mood
    return {
        "average_score": _num(_mean([day_values[d] for d in ordered])),
        "best_day": _extreme(ordered, day_values, True),
        "worst_day": _extreme(ordered, day_values, False),
        "tag_distribution": _mood_distribution(db, rows),
    }


def summary(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """S-03：统计摘要（窗口规则**与 S-02 完全一致**）。"""
    metric_type = _parse_metric(args)
    today = now_local().date()
    days, start, end = _resolve_window(args, today)
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.min) + timedelta(days=1)

    rows = _fetch_records(db, user_id, metric_type, start_dt, end_dt)
    days_map = _group_by_day(rows)
    day_values = _day_values(metric_type, days_map)
    ordered = sorted(day_values)
    goal = _active_goal(db, user_id, metric_type)

    if ordered:
        values = [day_values[d] for d in ordered]
        first, last = values[0], values[-1]
        body: Dict[str, Any] = {
            "average": _num(_mean(values)),
            "change": {
                "from": _num(first),
                "to": _num(last),
                "delta": _num(last - first),
                "from_date": ordered[0].isoformat(),
                "to_date": ordered[-1].isoformat(),
            },
            "max": _extreme(ordered, day_values, True),
            "min": _extreme(ordered, day_values, False),
            "reached_rate_percent": _reached_rate(metric_type, day_values, goal),
            "recorded_days": {
                "recorded": len(ordered),
                "total": days,
                "percent": round(len(ordered) / days * 100, 1),
            },
        }
    else:
        body = {
            "average": None,
            "change": None,
            "max": None,
            "min": None,
            "reached_rate_percent": None,
            "recorded_days": {"recorded": 0, "total": days, "percent": 0.0},
        }

    if metric_type == "bp" and ordered:
        # max/min 分别含收缩/舒张（S1-B §九 差异字段表）
        systolic = {d: _mean([r["value_1"] for r in days_map[d]]) for d in ordered}
        diastolic = {d: _mean([r["value_2"] for r in days_map[d]]) for d in ordered}
        for key, want_max in (("max", True), ("min", False)):
            target = (max if want_max else min)(systolic[d] for d in ordered)
            day = next(d for d in ordered if systolic[d] == target)
            body[key] = {
                "systolic": _num(systolic[day]),
                "diastolic": _num(diastolic[day]),
                "date": day.isoformat(),
            }

    if metric_type == "sleep":
        # 睡眠目标的达标率（S-03 差异字段显式要求）
        body["reached_rate_percent"] = _reached_rate(metric_type, day_values, goal)

    body.update(_summary_extras(
        db, user_id, metric_type, rows, days_map, day_values, goal, start, end
    ))

    return {
        "metric_type": metric_type,
        "unit": metric_rules.METRIC_UNIT[metric_type],
        "window": _window_payload(days, start, end),
        "summary": body,
    }


__all__ = ["WINDOW_DAYS", "DEFAULT_WINDOW", "home_overview", "trend", "summary"]
