# -*- coding: utf-8 -*-
"""S-03 ``GET /api/v1/stats/summary`` —— 统计摘要契约测试。

依据：《S1-B 第二批 API 接口设计文档》§九「S-03 统计摘要」+《S0》§9.2 / §9.3
"""
from __future__ import annotations

from datetime import date as _date, timedelta

from tests.batch5.conftest import (
    add_record,
    create_goal,
    day_str,
    dt_at,
    fmt,
    payload_of,
    summary,
    week_start_of,
)

API = "/api/v1"
TODAY = day_str(0)


# ════════════════════════════════════════════════════════════════════
# 鉴权 / 参数 / 空态
# ════════════════════════════════════════════════════════════════════
def test_s03_requires_auth(client):
    """S-03：缺 Token → 401。"""
    resp = client.get(f"{API}/stats/summary", query_string={"metric_type": "weight"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_s03_param_validation(client, user):
    """S-03：``metric_type`` 必填合法；``window`` 7/30/90；``end`` 格式；否则 400。"""
    assert summary(client, user["header"]).status_code == 400
    assert summary(client, user["header"], metric_type="xyz").status_code == 400
    assert summary(client, user["header"], metric_type="water", window=15).status_code == 400
    assert summary(client, user["header"], metric_type="water", end="abc").status_code == 400
    ok = summary(client, user["header"], metric_type="water", window=90)
    assert ok.status_code == 200
    assert ok.get_json()["data"]["window"] == {
        "days": 90, "start": day_str(-89), "end": TODAY,
    }


def test_s03_window_matches_s02(client, user):
    """S-03：窗口规则**与 S-02 完全一致**（同一参数 → 同一 window 块）。"""
    from tests.batch5.conftest import trend

    for query in ({"metric_type": "weight", "window": 30},
                  {"metric_type": "water", "window": 7, "end": day_str(-3)}):
        a = payload_of(trend(client, user["header"], **query))["window"]
        b = payload_of(summary(client, user["header"], **query))["window"]
        assert a == b, query


def test_s03_empty_window(client, user):
    """S-03：空窗口 → 5 项全 ``null``、``recorded_days={0, window, 0.0}``，**200**。"""
    data = payload_of(summary(client, user["header"], metric_type="water", window=7))
    assert data["metric_type"] == "water" and data["unit"] == "ml"
    body = data["summary"]
    assert body["average"] is None
    assert body["change"] is None
    assert body["max"] is None and body["min"] is None
    assert body["reached_rate_percent"] is None
    assert body["recorded_days"] == {"recorded": 0, "total": 7, "percent": 0.0}
    # water 差异字段：计数类为 0，均值类为 null
    assert body["daily_average_ml"] is None
    assert body["reached_day_count"] == 0
    assert body["longest_streak_days"] == 0


def test_s03_single_point_change_is_zero(client, user):
    """S-03：仅 1 个有记录日 → ``change.from == change.to``、``delta == 0``。"""
    add_record(client, user["header"], metric_type="weight", value_1=70.0,
               recorded_at=fmt(dt_at(-2, 9, 0)))
    body = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert body["average"] == 70
    assert body["change"] == {
        "from": 70, "to": 70, "delta": 0,
        "from_date": day_str(-2), "to_date": day_str(-2),
    }
    assert body["max"] == {"value": 70, "date": day_str(-2)}
    assert body["min"] == {"value": 70, "date": day_str(-2)}
    assert body["recorded_days"] == {"recorded": 1, "total": 7, "percent": 14.3}


# ════════════════════════════════════════════════════════════════════
# 通用 5 项
# ════════════════════════════════════════════════════════════════════
def test_s03_generic_five_items(client, user):
    """S-03：``average`` / ``change`` / ``max`` / ``min`` / ``recorded_days`` 逐值正确。"""
    for offset, value in ((-6, 72.0), (-4, 71.5), (-2, 71.0)):
        add_record(client, user["header"], metric_type="weight", value_1=value,
                   recorded_at=fmt(dt_at(offset, 9, 0)))
    body = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert body["average"] == 71.5
    assert body["change"] == {
        "from": 72, "to": 71, "delta": -1,
        "from_date": day_str(-6), "to_date": day_str(-2),
    }
    assert body["max"] == {"value": 72, "date": day_str(-6)}
    assert body["min"] == {"value": 71, "date": day_str(-2)}
    assert body["recorded_days"] == {"recorded": 3, "total": 7, "percent": 42.9}


def test_s03_extreme_tie_takes_earliest_date(client, user):
    """S-03：极值并列取**最早**出现日。"""
    for offset, value in ((-3, 70.0), (-2, 70.0), (-1, 69.0)):
        add_record(client, user["header"], metric_type="weight", value_1=value,
                   recorded_at=fmt(dt_at(offset, 9, 0)))
    body = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert body["max"] == {"value": 70, "date": day_str(-3)}   # 并列 → 最早
    assert body["min"] == {"value": 69, "date": day_str(-1)}


# ════════════════════════════════════════════════════════════════════
# 逐指标差异字段
# ════════════════════════════════════════════════════════════════════
def test_s03_weight_distance_to_target_and_rate_null(client, user):
    """S-03：``weight.distance_to_target``（无目标 → ``null``）；weight 达标率恒 ``null``。"""
    no_goal = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert no_goal["distance_to_target"] is None

    add_record(client, user["header"], metric_type="weight", value_1=71.0,
               recorded_at=fmt(dt_at(-2, 9, 0)))
    create_goal(client, user["header"], goal_type="weight", target_value=68.0,
                start_weight_kg=72.5)
    body = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert body["distance_to_target"] == 3          # 71.0 − 68.0
    assert body["reached_rate_percent"] is None     # weight 目标按 G-07 → 恒 null


def test_s03_bp_difference_fields(client, user):
    """S-03：``bp`` 差异字段 + ``max``/``min`` 含收缩/舒张。"""
    add_record(client, user["header"], metric_type="bp", value_1=120, value_2=80,
               recorded_at=fmt(dt_at(-2, 8, 0)))
    add_record(client, user["header"], metric_type="bp", value_1=130, value_2=90,
               recorded_at=fmt(dt_at(-1, 20, 0)))
    body = payload_of(summary(client, user["header"], metric_type="bp"))["summary"]
    assert body["average_systolic"] == 125
    assert body["average_diastolic"] == 85
    assert body["measure_count"] == 2
    assert body["max"] == {"systolic": 130, "diastolic": 90, "date": day_str(-1)}
    assert body["min"] == {"systolic": 120, "diastolic": 80, "date": day_str(-2)}
    assert body["reached_rate_percent"] is None     # bp 无目标类型


def test_s03_heart_resting_average(client, user):
    """S-03：``heart.resting_average`` 仅取 ``attr_1='resting'`` 子集。"""
    add_record(client, user["header"], metric_type="heart", value_1=60,
               attr_1="resting", recorded_at=fmt(dt_at(-2, 8, 0)))
    add_record(client, user["header"], metric_type="heart", value_1=100,
               attr_1="after_activity", recorded_at=fmt(dt_at(-1, 20, 0)))
    body = payload_of(summary(client, user["header"], metric_type="heart"))["summary"]
    assert body["resting_average"] == 60
    assert body["average"] == 80                    # (60 + 100) / 2

    empty = payload_of(summary(client, user["header"], metric_type="heart", end=day_str(-10)))
    assert empty["summary"]["resting_average"] is None


def test_s03_glucose_fasting_and_after_meal(client, user):
    """S-03：``glucose`` 空腹 / 餐后均值 + ``measure_count``。"""
    add_record(client, user["header"], metric_type="glucose", value_1=5.0,
               attr_1="fasting", recorded_at=fmt(dt_at(-2, 7, 0)))
    add_record(client, user["header"], metric_type="glucose", value_1=6.0,
               attr_1="fasting", recorded_at=fmt(dt_at(-1, 7, 0)))
    add_record(client, user["header"], metric_type="glucose", value_1=8.0,
               attr_1="after_meal_2h", recorded_at=fmt(dt_at(-1, 20, 0)))
    body = payload_of(summary(client, user["header"], metric_type="glucose"))["summary"]
    assert body["average_fasting"] == 5.5
    assert body["average_after_meal"] == 8
    assert body["measure_count"] == 3


def test_s03_sleep_fields_and_reached_rate(client, user):
    """S-03：``sleep`` 平均时长 / 最长最短（含日期）/ 平均质量 + 睡眠目标达标率。"""
    end = dt_at(-2, 7, 0)
    add_record(client, user["header"], metric_type="sleep", value_1=5,
               time_start=fmt(end - timedelta(hours=8, minutes=30)), recorded_at=fmt(end))
    end2 = dt_at(-1, 7, 0)
    add_record(client, user["header"], metric_type="sleep", value_1=4,
               time_start=fmt(end2 - timedelta(hours=6, minutes=30)), recorded_at=fmt(end2))

    body = payload_of(summary(client, user["header"], metric_type="sleep"))["summary"]
    assert body["average_duration_hours"] == 7.5
    assert body["average_quality"] == 4.5
    assert body["longest"] == {"value": 8.5, "date": day_str(-2)}
    assert body["shortest"] == {"value": 6.5, "date": day_str(-1)}
    assert body["reached_rate_percent"] is None      # 无睡眠目标

    create_goal(client, user["header"], goal_type="sleep", target_value=8)
    with_goal = payload_of(summary(client, user["header"], metric_type="sleep"))["summary"]
    assert with_goal["reached_rate_percent"] == 50.0  # 2 天中 1 天达标（8.5 ≥ 8）


def test_s03_water_fields_and_reached_rate(client, user):
    """S-03：``water`` 日均 / 达标天数 / 达标率 / 最长连续达标。"""
    for offset in (-3, -2, -1):
        add_record(client, user["header"], metric_type="water", value_1=1000,
                   recorded_at=fmt(dt_at(offset, 8, 0)))
        add_record(client, user["header"], metric_type="water", value_1=1000,
                   recorded_at=fmt(dt_at(offset, 20, 0)))
    create_goal(client, user["header"], goal_type="water", target_value=2000)

    body = payload_of(summary(client, user["header"], metric_type="water"))["summary"]
    assert body["average"] == 2000
    assert body["daily_average_ml"] == 2000
    assert body["reached_day_count"] == 3
    assert body["reached_rate_percent"] == 100.0
    assert body["longest_streak_days"] == 3


def test_s03_water_reached_rate_null_without_goal(client, user):
    """S-03：无自设目标 → ``reached_rate_percent: null``（服务端不返"未设目标"文案）。"""
    add_record(client, user["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    body = payload_of(summary(client, user["header"], metric_type="water"))["summary"]
    assert body["reached_rate_percent"] is None
    assert body["reached_day_count"] == 0


def test_s03_sport_fields(client, user):
    """S-03：``sport`` 总时长 / 日均 / 次数 / 达标周数 / 周均。"""
    add_record(client, user["header"], metric_type="sport", value_1=30,
               attr_1="running", recorded_at=fmt(dt_at(-1, 9, 0)))
    add_record(client, user["header"], metric_type="sport", value_1=45,
               attr_1="walking", recorded_at=fmt(dt_at(-1, 10, 0)))

    body = payload_of(summary(client, user["header"], metric_type="sport"))["summary"]
    assert body["total_minutes"] == 75
    assert body["daily_average_minutes"] == 75
    assert body["session_count"] == 2
    assert body["reached_week_count"] == 0          # 无目标
    weeks = len({week_start_of(_date.fromisoformat(day_str(-i))) for i in range(7)})
    assert body["weekly_average_minutes"] == 75 / weeks


def test_s03_mood_fields(client, user):
    """S-03：``mood`` 平均分 / 最好最差日 / 标签分布。"""
    add_record(client, user["header"], metric_type="mood", value_1=4,
               tags=["relaxed"], recorded_at=fmt(dt_at(-2, 9, 0)))
    add_record(client, user["header"], metric_type="mood", value_1=2,
               tags=["tired", "relaxed"], recorded_at=fmt(dt_at(-1, 9, 0)))
    body = payload_of(summary(client, user["header"], metric_type="mood"))["summary"]
    assert body["average_score"] == 3
    assert body["best_day"] == {"value": 4, "date": day_str(-2)}
    assert body["worst_day"] == {"value": 2, "date": day_str(-1)}
    assert body["tag_distribution"] == [
        {"tag": "tired", "count": 1},
        {"tag": "relaxed", "count": 2},
    ]
    assert body["reached_rate_percent"] is None


# ════════════════════════════════════════════════════════════════════
# 隔离 / 软删
# ════════════════════════════════════════════════════════════════════
def test_s03_soft_deleted_excluded(client, user):
    """S-03：软删记录不参与统计。"""
    created = add_record(client, user["header"], metric_type="weight", value_1=72.0,
                         recorded_at=fmt(dt_at(-2, 9, 0)))
    add_record(client, user["header"], metric_type="weight", value_1=70.0,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    assert payload_of(summary(client, user["header"],
                              metric_type="weight"))["summary"]["recorded_days"]["recorded"] == 2

    assert client.delete(f"{API}/records/{created['record']['id']}",
                         headers=user["header"]).status_code == 200
    body = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert body["recorded_days"]["recorded"] == 1
    assert body["average"] == 70


def test_s03_user_isolation(client, user, peer):
    """S-03：跨用户**零泄漏**。"""
    add_record(client, peer["header"], metric_type="weight", value_1=90.0,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    body = payload_of(summary(client, user["header"], metric_type="weight"))["summary"]
    assert body["average"] is None
    assert body["recorded_days"]["recorded"] == 0
