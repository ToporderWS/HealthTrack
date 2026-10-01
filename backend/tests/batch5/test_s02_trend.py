# -*- coding: utf-8 -*-
"""S-02 ``GET /api/v1/stats/trend`` —— 趋势数据契约测试。

依据：《S1-B 第二批 API 接口设计文档》§九「S-02 趋势数据」+《S0》§9.2 / §9.4
"""
from __future__ import annotations

from datetime import timedelta

from tests.batch5.conftest import (
    add_record,
    create_goal,
    day_str,
    dt_at,
    fmt,
    payload_of,
    trend,
)

API = "/api/v1"
TODAY = day_str(0)


# ════════════════════════════════════════════════════════════════════
# 鉴权 / 参数
# ════════════════════════════════════════════════════════════════════
def test_s02_requires_auth(client):
    """S-02：缺 Token → 401。"""
    resp = client.get(f"{API}/stats/trend", query_string={"metric_type": "water"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_s02_metric_type_required_and_validated(client, user):
    """S-02：``metric_type`` 必填且必须为 8 类之一，否则 400。"""
    for query in ({}, {"metric_type": ""}, {"metric_type": "blood"},
                  {"metric_type": "WATER"}, {"metric_type": "bp2"}):
        resp = trend(client, user["header"], **query)
        assert resp.status_code == 400, query
        assert resp.get_json()["code"] == "INVALID_PARAM", query


def test_s02_window_allowed_values_and_default(client, user):
    """S-02：``window`` 仅 7/30/90（默认 **7**）；非法 → 400。"""
    default = payload_of(trend(client, user["header"], metric_type="water"))
    assert default["window"] == {"days": 7, "start": day_str(-6), "end": TODAY}

    for window in (7, 30, 90):
        data = payload_of(trend(client, user["header"], metric_type="water", window=window))
        assert data["window"]["days"] == window
        assert data["window"]["start"] == day_str(-(window - 1))
        assert data["window"]["end"] == TODAY

    for bad in (0, 1, 14, 31, 91, -7, "abc", "7.5"):
        resp = trend(client, user["header"], metric_type="water", window=bad)
        assert resp.status_code == 400, bad
        assert resp.get_json()["code"] == "INVALID_PARAM", bad


def test_s02_end_defaults_today_and_validates_format(client, user):
    """S-02：``end`` 默认今天；非法格式 → 400。"""
    assert payload_of(trend(client, user["header"], metric_type="water"))["window"]["end"] == TODAY
    for bad in ("2026-9-1", "2026/09/01", "abc", "2026-13-01"):
        resp = trend(client, user["header"], metric_type="water", end=bad)
        assert resp.status_code == 400, bad
        assert resp.get_json()["code"] == "INVALID_PARAM", bad


def test_s02_future_end_allowed_and_returns_empty(client, user):
    """S-02（T-4）：``end`` 允许未来日期（仅格式校验）；无记录 → 空数据，**200**。"""
    add_record(client, user["header"], metric_type="water", value_1=1500,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    # 未来 100 天窗口内必然无该用户记录 → 正常返回空，不人为清空、不报错
    data = payload_of(trend(client, user["header"], metric_type="water", end=day_str(100)))
    assert data["window"]["end"] == day_str(100)
    assert data["points"] == []
    assert data["insufficient_data"] is True

    # 历史窗口（end 指向过去）同样正常返回
    history = payload_of(trend(client, user["header"], metric_type="water", end=day_str(-1)))
    assert history["window"]["end"] == day_str(-1)
    assert history["points"] == [{"date": day_str(-1), "total_ml": 1500}]


# ════════════════════════════════════════════════════════════════════
# 骨架 / 时间边界 / 缺失日期
# ════════════════════════════════════════════════════════════════════
def test_s02_envelope_skeleton(client, user):
    """S-02：响应骨架字段齐全（``metric_type``/``unit``/``window``/``chart``/
    ``insufficient_data``/``points``）。"""
    data = payload_of(trend(client, user["header"], metric_type="water"))
    assert set(data) >= {"metric_type", "unit", "window", "chart", "insufficient_data", "points"}
    assert data["metric_type"] == "water"
    assert data["unit"] == "ml"
    assert data["chart"] == "bar"
    assert set(data["window"]) == {"days", "start", "end"}


def test_s02_chart_type_per_metric(client, user):
    """S-02：``chart`` 逐指标（折线 5 类 / 柱状 3 类）。"""
    expect = {"weight": "line", "bp": "line", "heart": "line", "glucose": "line",
              "mood": "line", "sleep": "bar", "water": "bar", "sport": "bar"}
    for metric, chart in expect.items():
        data = payload_of(trend(client, user["header"], metric_type=metric))
        assert data["chart"] == chart, metric


def test_s02_window_half_open_boundaries(client, user):
    """S-02：半开区间 ``[start 00:00:00, end+1d 00:00:00)`` 精确边界。"""
    add_record(client, user["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-6, 0, 0, 0)))        # == start → **含**
    add_record(client, user["header"], metric_type="water", value_1=2000,
               recorded_at=fmt(dt_at(-7, 23, 59, 59)))     # start −1s → **不含**
    add_record(client, user["header"], metric_type="water", value_1=300,
               recorded_at=fmt(dt_at(-5, 0, 0, 0)))        # 次日 00:00:00 → **含**

    data = payload_of(trend(client, user["header"], metric_type="water"))
    assert data["points"] == [
        {"date": day_str(-6), "total_ml": 1000},
        {"date": day_str(-5), "total_ml": 300},
    ]


def test_s02_end_day_last_second_included(client, user):
    """S-02：``end`` 当日 ``23:59:59`` 属于窗口内。"""
    add_record(client, user["header"], metric_type="water", value_1=500,
               recorded_at=fmt(dt_at(-1, 23, 59, 59)))
    data = payload_of(trend(client, user["header"], metric_type="water"))
    assert data["points"] == [{"date": day_str(-1), "total_ml": 500}]


def test_s02_missing_dates_not_filled(client, user):
    """S-02：缺失日期**不补零、不插值**（数组只含实际有记录的日）。"""
    for offset in (-6, -4, -2):
        add_record(client, user["header"], metric_type="water", value_1=1000,
                   recorded_at=fmt(dt_at(offset, 9, 0)))
    dates = [p["date"] for p in payload_of(
        trend(client, user["header"], metric_type="water"))["points"]]
    assert dates == [day_str(-6), day_str(-4), day_str(-2)]


def test_s02_insufficient_data_threshold(client, user):
    """S-02：``insufficient_data = points.length < 2``。"""
    assert payload_of(trend(client, user["header"], metric_type="water"))["insufficient_data"] is True

    add_record(client, user["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-3, 9, 0)))
    one = payload_of(trend(client, user["header"], metric_type="water"))
    assert len(one["points"]) == 1 and one["insufficient_data"] is True

    add_record(client, user["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-2, 9, 0)))
    two = payload_of(trend(client, user["header"], metric_type="water"))
    assert len(two["points"]) == 2 and two["insufficient_data"] is False


def test_s02_same_day_two_points_same_date_grouped(client, user):
    """S-02：同日多条记录**聚合为一个点**（同日不产生两个数据点）。"""
    add_record(client, user["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-2, 8, 0)))
    add_record(client, user["header"], metric_type="water", value_1=500,
               recorded_at=fmt(dt_at(-2, 20, 0)))
    points = payload_of(trend(client, user["header"], metric_type="water"))["points"]
    assert points == [{"date": day_str(-2), "total_ml": 1500}]


# ════════════════════════════════════════════════════════════════════
# 逐指标日聚合口径
# ════════════════════════════════════════════════════════════════════
def test_s02_weight_last_of_day_and_decimal_normalization(client, user):
    """S-02：``weight`` 当日**取最后一次**；``Decimal`` 输出归一（70.50 → 70.5；70.00 → 70）。"""
    add_record(client, user["header"], metric_type="weight", value_1=70.50,
               recorded_at=fmt(dt_at(-3, 8, 0)))
    add_record(client, user["header"], metric_type="weight", value_1=71.50,
               recorded_at=fmt(dt_at(-3, 20, 0)))
    add_record(client, user["header"], metric_type="weight", value_1=70.00,
               recorded_at=fmt(dt_at(-2, 9, 0)))

    points = payload_of(trend(client, user["header"], metric_type="weight"))["points"]
    assert points == [
        {"date": day_str(-3), "value": 71.5},   # 最后一次（非均值）
        {"date": day_str(-2), "value": 70},     # 整数归一为 int
    ]
    assert isinstance(points[1]["value"], int) and not isinstance(points[1]["value"], bool)


def test_s02_water_daily_sum_and_target_line(client, user):
    """S-02：``water`` 当日累计 ``SUM``；``target_line`` 来自用户自设目标。"""
    add_record(client, user["header"], metric_type="water", value_1=1500,
               recorded_at=fmt(dt_at(-2, 9, 0)))
    add_record(client, user["header"], metric_type="water", value_1=900,
               recorded_at=fmt(dt_at(-2, 21, 0)))

    none_goal = payload_of(trend(client, user["header"], metric_type="water"))
    assert none_goal["points"] == [{"date": day_str(-2), "total_ml": 2400}]
    assert none_goal["target_line"] is None

    created = create_goal(client, user["header"], goal_type="water", target_value=2000)
    assert created.status_code == 201, created.get_json()
    goal_id = created.get_json()["data"]["goal"]["id"]
    with_goal = payload_of(trend(client, user["header"], metric_type="water"))
    assert with_goal["target_line"] == {
        "value": 2000, "unit": "ml", "source": "health_goal", "goal_id": goal_id,
    }


def test_s02_weight_target_line_from_weight_goal(client, user):
    """S-02：``weight`` 亦有 ``target_line``（用户自设目标体重）。"""
    created = create_goal(client, user["header"], goal_type="weight",
                          target_value=68.0, start_weight_kg=72.5)
    goal_id = created.get_json()["data"]["goal"]["id"]
    add_record(client, user["header"], metric_type="weight", value_1=71.0,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    data = payload_of(trend(client, user["header"], metric_type="weight"))
    assert data["target_line"] == {
        "value": 68, "unit": "kg", "source": "health_goal", "goal_id": goal_id,
    }


def test_s02_no_target_line_key_for_other_metrics(client, user):
    """S-02：``target_line`` **仅** weight/water 输出该键。"""
    for metric in ("bp", "heart", "glucose", "sleep", "sport", "mood"):
        data = payload_of(trend(client, user["header"], metric_type=metric))
        assert "target_line" not in data, metric


def test_s02_bp_daily_average_two_values(client, user):
    """S-02：``bp`` 当日 ``value_1``/``value_2`` **算术平均**。"""
    add_record(client, user["header"], metric_type="bp", value_1=120, value_2=80,
               recorded_at=fmt(dt_at(-2, 8, 0)))
    add_record(client, user["header"], metric_type="bp", value_1=130, value_2=90,
               recorded_at=fmt(dt_at(-2, 20, 0)))
    points = payload_of(trend(client, user["header"], metric_type="bp"))["points"]
    assert points == [{"date": day_str(-2), "systolic": 125, "diastolic": 85}]


def test_s02_heart_daily_average(client, user):
    """S-02：``heart`` 当日 ``value_1`` 平均。"""
    add_record(client, user["header"], metric_type="heart", value_1=70,
               recorded_at=fmt(dt_at(-2, 8, 0)))
    add_record(client, user["header"], metric_type="heart", value_1=80,
               recorded_at=fmt(dt_at(-2, 20, 0)))
    points = payload_of(trend(client, user["header"], metric_type="heart"))["points"]
    assert points == [{"date": day_str(-2), "value": 75}]


def test_s02_glucose_groups_only_with_group_by_timing(client, user):
    """S-02：``groups`` **仅** ``glucose``+``group_by=timing``；按枚举固定序。"""
    add_record(client, user["header"], metric_type="glucose", value_1=5.5,
               attr_1="fasting", recorded_at=fmt(dt_at(-2, 7, 0)))
    add_record(client, user["header"], metric_type="glucose", value_1=6.5,
               attr_1="fasting", recorded_at=fmt(dt_at(-1, 7, 0)))
    add_record(client, user["header"], metric_type="glucose", value_1=8.0,
               attr_1="after_meal_2h", recorded_at=fmt(dt_at(-1, 20, 0)))

    plain = payload_of(trend(client, user["header"], metric_type="glucose"))
    assert "groups" not in plain
    assert plain["points"] == [
        {"date": day_str(-2), "value": 5.5},
        {"date": day_str(-1), "value": 7.25},
    ]

    grouped = payload_of(trend(client, user["header"], metric_type="glucose",
                               group_by="timing"))
    assert grouped["groups"] == [
        {"timing": "fasting", "value": 6},        # (5.5 + 6.5) / 2
        {"timing": "after_meal_2h", "value": 8},
    ]


def test_s02_group_by_rejected_for_unsupported_metric(client, user):
    """S-02：``group_by`` 不被该指标支持 → 400。"""
    for query in ({"metric_type": "water", "group_by": "timing"},
                  {"metric_type": "glucose", "group_by": "tag"},
                  {"metric_type": "mood", "group_by": "timing"},
                  {"metric_type": "water", "group_by": "tag"},
                  {"metric_type": "glucose", "group_by": "xyz"}):
        resp = trend(client, user["header"], **query)
        assert resp.status_code == 400, query
        assert resp.get_json()["code"] == "INVALID_PARAM", query


def test_s02_sleep_duration_sum_and_quality_average(client, user):
    """S-02：``sleep`` 时长当日**累计**（1 位小数）+ 质量均分。"""
    end = dt_at(-2, 7, 0)
    add_record(client, user["header"], metric_type="sleep", value_1=5,
               time_start=fmt(end - timedelta(hours=3)), recorded_at=fmt(end))
    add_record(client, user["header"], metric_type="sleep", value_1=4,
               time_start=fmt(end - timedelta(hours=4, minutes=30)), recorded_at=fmt(end))

    data = payload_of(trend(client, user["header"], metric_type="sleep"))
    assert data["unit"] == "score"
    assert data["points"] == [
        {"date": day_str(-2), "duration_hours": 7.5, "quality": 4.5},
    ]


def test_s02_sport_minutes_count_and_weekly(client, user):
    """S-02：``sport`` 当日累计分钟 + 条数；``weekly`` 周汇总（``week_start``=周一）。"""
    add_record(client, user["header"], metric_type="sport", value_1=30,
               attr_1="running", recorded_at=fmt(dt_at(-1, 9, 0)))
    add_record(client, user["header"], metric_type="sport", value_1=45,
               attr_1="walking", recorded_at=fmt(dt_at(-1, 10, 0)))

    data = payload_of(trend(client, user["header"], metric_type="sport"))
    assert data["points"] == [{"date": day_str(-1), "minutes": 75, "count": 2}]
    assert len(data["weekly"]) == 1
    week = data["weekly"][0]
    assert set(week) == {"week_start", "minutes", "count"}
    assert week["minutes"] == 75 and week["count"] == 2
    # week_start 必须为**周一**
    from datetime import date as _date

    assert _date.fromisoformat(week["week_start"]).weekday() == 0


def test_s02_mood_average_and_tag_distribution_order(client, user):
    """S-02：``mood`` 当日均分；``tag_distribution`` 按 ``mood_tags`` 固定序，仅出现 ≥1。"""
    add_record(client, user["header"], metric_type="mood", value_1=4,
               tags=["relaxed"], recorded_at=fmt(dt_at(-2, 9, 0)))
    add_record(client, user["header"], metric_type="mood", value_1=2,
               tags=["tired", "relaxed"], recorded_at=fmt(dt_at(-1, 9, 0)))

    data = payload_of(trend(client, user["header"], metric_type="mood"))
    assert data["points"] == [
        {"date": day_str(-2), "value": 4},
        {"date": day_str(-1), "value": 2},
    ]
    # 枚举顺序：tired, anxious, relaxed, focused, low, energetic
    assert data["tag_distribution"] == [
        {"tag": "tired", "count": 1},
        {"tag": "relaxed", "count": 2},
    ]


def test_s02_soft_deleted_records_excluded(client, user):
    """S-02：``is_deleted=1`` 的记录**完全不参与**聚合。"""
    created = add_record(client, user["header"], metric_type="water", value_1=1500,
                         recorded_at=fmt(dt_at(-2, 9, 0)))
    add_record(client, user["header"], metric_type="water", value_1=300,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    before = payload_of(trend(client, user["header"], metric_type="water"))

    deleted = client.delete(f"{API}/records/{created['record']['id']}",
                            headers=user["header"])
    assert deleted.status_code == 200
    after = payload_of(trend(client, user["header"], metric_type="water"))
    assert before["points"] == [
        {"date": day_str(-2), "total_ml": 1500},
        {"date": day_str(-1), "total_ml": 300},
    ]
    assert after["points"] == [{"date": day_str(-1), "total_ml": 300}]


def test_s02_user_isolation(client, user, peer):
    """S-02：跨用户**零泄漏**（对端记录不出现在本端趋势）。"""
    add_record(client, peer["header"], metric_type="water", value_1=1500,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    data = payload_of(trend(client, user["header"], metric_type="water"))
    assert data["points"] == []
    assert data["insufficient_data"] is True
