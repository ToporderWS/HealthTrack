# -*- coding: utf-8 -*-
"""健康目标完成度聚合（G-07）——**独立文件**。

依据：
- 《S1-B 第二批 API 接口设计文档》§八 G-07
- 《S0-产品规划报告》§8.1 ~ 8.2（完成度算法，**逐条一致，开发强制依据**）

算法（**派生值不落库**，实时计算）：

| 目标 | 周期 | 算法 |
|---|---|---|
| ``weight`` | ``once`` | ``(当前体重 − 起始体重) ÷ (目标值 − 起始体重) × 100%``（增重 / 减重方向**同一公式自动成立**） |
| ``water`` | ``daily`` | 当日累计 ``SUM(value_1)`` ÷ 目标值 × 100%（半开区间 ``[今日00:00:00, 明日00:00:00)``） |
| ``sport`` | ``weekly`` | 本周累计 ÷ 目标值 × 100%（``attr_1='count'`` 累计次数、``'min'`` 累计 ``value_1``；周 = ``[周一00:00:00, 下周一00:00:00)``） |
| ``sleep`` | ``daily`` | 当日派生睡眠时长（``time_start → recorded_at``，复用 ``metric_rules.sleep_duration_hours``）÷ 目标值 × 100% |

**保护口径（不补零、不估算）**：
- ``weight`` 的起始体重为空或**无任何体重记录** → ``progress_percent`` / ``remaining_value``
  / ``remaining_text`` 均为 ``NULL``；
- ``rate`` **仅对有"每日 / 每周"周期的目标计算**，``weight`` 恒为 ``NULL``；
- ``days_recorded`` 仅统计窗口内**实际有记录的天数**，**缺失日期不补零**；
  ``days_recorded == 0`` → ``reached_rate_percent = NULL``。

**红线**：只陈述数字事实；``remaining_text`` 仅给数字与单位，**不含任何评价词 / 医学结论**
（客户端不使用红绿好坏语义色）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode
from app.core.security import now_local
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.services import goal_service, metric_rules, profile_service

#: 允许的达标率窗口（其他值 → ``400 INVALID_PARAM``）
WINDOW_DAYS: Tuple[int, ...] = (7, 30, 90)
DEFAULT_WINDOW = 30


def _num(value: Optional[Decimal]) -> Optional[Any]:
    """数值输出：整数值输出 ``int``，否则 ``float``。"""
    if value is None:
        return None
    dec = Decimal(value)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _pct(numerator: Decimal, denominator: Decimal) -> Optional[float]:
    if denominator is None or Decimal(denominator) == 0:
        return None
    return round(float(Decimal(numerator) / Decimal(denominator) * Decimal(100)), 1)


def _day_bounds(day: date) -> Tuple[datetime, datetime]:
    """半开区间 ``[当日 00:00:00, 次日 00:00:00)``。"""
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def _week_start(day: date) -> date:
    """本周起点（**周一**）。"""
    return day - timedelta(days=day.weekday())


def _daily_totals(db: Session, user_id: int, metric: str, attr_1: Optional[str],
                  start_dt: datetime, end_dt: datetime) -> Dict[date, Decimal]:
    """按 ``recorded_at`` 归属日聚合（``is_deleted=0``；**缺失日期不补零**）。

    - ``water``  → 当日 ``SUM(value_1)``
    - ``sleep``  → 当日派生睡眠时长合计（小时，``time_start → recorded_at``）
    - ``sport``  → ``attr_1='count'`` 当日**记录条数**；``'min'`` 当日 ``SUM(value_1)``
    """
    rows = db.execute(
        select(HealthRecord.recorded_at, HealthRecord.value_1, HealthRecord.time_start).where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == metric,
            HealthRecord.is_deleted == 0,
            HealthRecord.recorded_at >= start_dt,
            HealthRecord.recorded_at < end_dt,
        )
    ).all()

    totals: Dict[date, Decimal] = {}
    for recorded_at, value_1, time_start in rows:
        day = recorded_at.date()
        if metric == "sleep":
            hours = metric_rules.sleep_duration_hours(
                {"time_start": time_start, "recorded_at": recorded_at}
            )
            inc = Decimal(hours) if hours is not None else Decimal(0)
        elif metric == "sport" and attr_1 == "count":
            inc = Decimal(1)
        else:
            inc = Decimal(value_1) if value_1 is not None else Decimal(0)
        totals[day] = totals.get(day, Decimal(0)) + inc
    return totals


def _weight_progress(db: Session, user_id: int, goal: HealthGoal) -> Dict[str, Any]:
    """``weight``：完成度 = (当前体重 − 起始体重) ÷ (目标值 − 起始体重) × 100%。"""
    target = Decimal(goal.target_value)
    record = profile_service.latest_weight(db, user_id)
    current: Optional[Decimal] = None
    if record is not None and record.value_1 is not None:
        current = Decimal(record.value_1)
    start: Optional[Decimal] = None
    if goal.start_weight_kg is not None:
        start = Decimal(goal.start_weight_kg)

    if start is None or current is None or start == target:
        return {
            "current_value": _num(current),
            "progress_percent": None,
            "is_reached": False,
            "remaining_value": None,
            "remaining_text": None,
        }

    percent = _pct(current - start, target - start)
    reached = percent is not None and percent >= 100
    remaining = Decimal(0) if reached else abs(target - current)
    return {
        "current_value": _num(current),
        "progress_percent": percent,
        "is_reached": reached,
        "remaining_value": _num(remaining),
        "remaining_text": f"还差 {_num(remaining)} {goal.unit}",
    }


def _accumulate_progress(db: Session, user_id: int, goal: HealthGoal,
                         today: date) -> Dict[str, Any]:
    """``water`` / ``sport`` / ``sleep``：窗口累计 ÷ 目标值 × 100%（允许 > 100%）。"""
    target = Decimal(goal.target_value)
    if goal.period_type == "weekly":
        fetch_start = datetime.combine(_week_start(today), time.min)
        fetch_end = fetch_start + timedelta(days=7)
    else:
        fetch_start, fetch_end = _day_bounds(today)

    totals = _daily_totals(db, user_id, goal.goal_type, goal.attr_1, fetch_start, fetch_end)
    current = sum(totals.values(), Decimal(0))

    percent = _pct(current, target)
    reached = current >= target
    remaining = Decimal(0) if reached else (target - current)
    return {
        "current_value": _num(current),
        "progress_percent": percent,
        "is_reached": reached,
        "remaining_value": _num(remaining),
        "remaining_text": f"还差 {_num(remaining)} {goal.unit}",
    }


def _rate(db: Session, user_id: int, goal: HealthGoal, rate_window: int,
          today: date) -> Optional[Dict[str, Any]]:
    """达标率（**仅每日 / 每周周期目标**；``weight`` 恒 ``None``）。

    - ``days_recorded`` = 窗口内**实际有记录的天数**（缺失日期不计入、**不补零**）；
    - ``days_reached``  = 窗口内达标天数
      （每日目标按当日累计；每周目标按"当日所属周"的周累计判定）；
    - ``reached_rate_percent`` = ``days_reached ÷ days_recorded × 100``，
      ``days_recorded == 0`` → ``None``（不除零）。
    """
    if goal.goal_type == "weight" or goal.period_type not in ("daily", "weekly"):
        return None

    window_start = today - timedelta(days=rate_window - 1)
    _, window_end = _day_bounds(today)
    if goal.period_type == "weekly":
        fetch_start = _week_start(window_start)
    else:
        fetch_start = window_start
    start_dt = datetime.combine(fetch_start, time.min)

    totals = _daily_totals(db, user_id, goal.goal_type, goal.attr_1, start_dt, window_end)
    target = Decimal(goal.target_value)

    days = [window_start + timedelta(days=i) for i in range(rate_window)]
    recorded = [d for d in days if d in totals]

    if goal.period_type == "weekly":
        week_totals: Dict[date, Decimal] = {}
        for day, value in totals.items():
            key = _week_start(day)
            week_totals[key] = week_totals.get(key, Decimal(0)) + value
        reached = [d for d in recorded
                   if week_totals.get(_week_start(d), Decimal(0)) >= target]
    else:
        reached = [d for d in recorded if totals[d] >= target]

    n_recorded = len(recorded)
    n_reached = len(reached)
    return {
        "window_days": rate_window,
        "days_recorded": n_recorded,
        "days_reached": n_reached,
        "reached_rate_percent": round(n_reached / n_recorded * 100, 1) if n_recorded else None,
    }


def _progress_one(db: Session, user_id: int, goal: HealthGoal, rate_window: int,
                  today: date) -> Dict[str, Any]:
    if goal.goal_type == "weight":
        derived = _weight_progress(db, user_id, goal)
    else:
        derived = _accumulate_progress(db, user_id, goal, today)

    return {
        "goal_id": int(goal.id),
        "goal_type": goal.goal_type,
        "target_value": _num(goal.target_value),
        "unit": goal.unit,
        "status": int(goal.status),
        **derived,
        "period_label": goal_service.PERIOD_LABEL.get(goal.period_type, "overall"),
        "rate": _rate(db, user_id, goal, rate_window, today),
    }


def list_progress(db: Session, user_id: int, args: Dict[str, Any]) -> Dict[str, Any]:
    """G-07：目标完成度列表（**不分页**）。"""
    rate_window = goal_service.query_int(args, "rate_window")
    if rate_window is None:
        rate_window = DEFAULT_WINDOW
    if rate_window not in WINDOW_DAYS:
        raise ApiError(ErrorCode.INVALID_PARAM)

    goal_id = goal_service.query_int(args, "goal_id")
    today = now_local().date()

    if goal_id is not None:
        goals: List[HealthGoal] = [goal_service.find_owned_goal(db, user_id, goal_id)]
    else:
        goals = list(db.execute(
            select(HealthGoal)
            .where(HealthGoal.user_id == user_id, HealthGoal.is_deleted == 0)
            .order_by(HealthGoal.goal_type.asc(), HealthGoal.id.asc())
        ).scalars().all())

    return {
        "items": [_progress_one(db, user_id, goal, rate_window, today) for goal in goals],
    }


__all__ = ["WINDOW_DAYS", "DEFAULT_WINDOW", "list_progress"]
