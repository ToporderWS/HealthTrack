# -*- coding: utf-8 -*-
"""S2 第四批 —— G-07 目标完成度（四类算法 + 达标率窗口）。

★ 算法逐条对照《S1-B》§八 G-07 / 《S0》§8.1：
``weight`` 一次性 / ``water`` 当日 / ``sport`` 本周 / ``sleep`` 当日派生时长；
``rate`` 仅每日 / 每周目标；缺失日期**不补零**；``days_recorded=0`` → ``null``。
"""
from __future__ import annotations

from datetime import timedelta

from tests.batch4.conftest import (
    API,
    create_goal,
    created_goal,
    dt_at,
    fmt,
    post_record,
    week_start_offset,
)
from app.core.security import now_local

PROGRESS_KEYS = {"goal_id", "goal_type", "target_value", "unit", "status", "current_value",
                 "progress_percent", "is_reached", "remaining_value", "remaining_text",
                 "period_label", "rate"}


def _progress(client, header, **query):
    return client.get(f"{API}/goals/progress", headers=header,
                      query_string=query or None)


def _add(client, header, **payload):
    resp = post_record(client, header, payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["record"]


def _today(moment_offset_hours: int = -1) -> str:
    """今日的一个**已过去**的时点（默认 1 小时前；跨零点时回落为当前时间）。"""
    now = now_local()
    candidate = now - timedelta(hours=abs(moment_offset_hours))
    return fmt(candidate if candidate.date() == now.date() else now)


# ════════════════════════════════════════════════════════════════════
# 通用
# ════════════════════════════════════════════════════════════════════
def test_g07_empty_items_when_no_goal(client, user):
    """G-07：无目标 → ``items: []``（服务端不返回"未设目标"文案）。"""
    resp = _progress(client, user["header"])
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK"
    assert body["data"]["items"] == []


def test_g07_item_keys_and_goal_id_selection(client, user):
    """G-07：条目字段齐全；``goal_id`` 只返回指定目标。"""
    water = created_goal(create_goal(client, user["header"],
                                     goal_type="water", target_value=2000))
    created_goal(create_goal(client, user["header"], goal_type="sleep", target_value=8))
    items = _progress(client, user["header"]).get_json()["data"]["items"]
    assert len(items) == 2
    for item in items:
        assert set(item.keys()) == PROGRESS_KEYS, item

    one = _progress(client, user["header"], goal_id=water["id"]).get_json()["data"]["items"]
    assert [i["goal_id"] for i in one] == [water["id"]]


# ════════════════════════════════════════════════════════════════════
# water —— 当日半开区间
# ════════════════════════════════════════════════════════════════════
def test_g07_water_daily_aggregate_matches_contract_example(client, user):
    """G-07：``water`` 当日聚合 → 与契约示例逐值一致（1500/2000 = 75.0）。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=2000))
    _add(client, user["header"], metric_type="water", value_1=1000, recorded_at=_today())
    _add(client, user["header"], metric_type="water", value_1=500,
         recorded_at=fmt(now_local()))

    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 1500
    assert item["progress_percent"] == 75.0
    assert item["is_reached"] is False
    assert item["remaining_value"] == 500
    assert item["remaining_text"] == "还差 500 ml"
    assert item["period_label"] == "today"
    assert item["unit"] == "ml" and item["target_value"] == 2000


def test_g07_water_excludes_previous_day(client, user):
    """G-07：``water`` 半开区间 ``[今日00:00:00, 明日00:00:00)`` —— 昨日不串入。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=2000))
    _add(client, user["header"], metric_type="water", value_1=800,
         recorded_at=fmt(dt_at(-1, 23, 0)))          # 昨日 23:00 → 不计入
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 0
    assert item["progress_percent"] == 0.0
    assert item["remaining_text"] == "还差 2000 ml"

    _add(client, user["header"], metric_type="water", value_1=2000, recorded_at=_today())
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 2000
    assert item["progress_percent"] == 100.0
    assert item["is_reached"] is True
    assert item["remaining_value"] == 0


def test_g07_water_allows_over_target(client, user):
    """G-07：``water`` **允许 > 100%**（超额）。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=2000))
    _add(client, user["header"], metric_type="water", value_1=1500, recorded_at=_today())
    _add(client, user["header"], metric_type="water", value_1=1000, recorded_at=fmt(now_local()))
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 2500
    assert item["progress_percent"] == 125.0
    assert item["is_reached"] is True
    assert item["remaining_value"] == 0


# ════════════════════════════════════════════════════════════════════
# weight —— 一次性（含增重方向）
# ════════════════════════════════════════════════════════════════════
def test_g07_weight_loss_direction(client, user):
    """G-07：``weight`` 减重方向 ``(当前−起始)÷(目标−起始)``。"""
    created_goal(create_goal(client, user["header"], goal_type="weight",
                             target_value=68.0, start_weight_kg=72.5))
    _add(client, user["header"], metric_type="weight", value_1=71.2, recorded_at=_today())
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 71.2
    assert item["progress_percent"] == 28.9          # (-1.3) / (-4.5) = 28.9%
    assert item["is_reached"] is False
    assert item["remaining_value"] == 3.2
    assert item["remaining_text"] == "还差 3.2 kg"
    assert item["period_label"] == "overall"
    assert item["rate"] is None                      # weight 恒 null


def test_g07_weight_gain_direction(client, user):
    """G-07：``weight`` **增重方向必须正确处理**（同一公式自动成立）。"""
    created_goal(create_goal(client, user["header"], goal_type="weight",
                             target_value=75.0, start_weight_kg=70.0))
    _add(client, user["header"], metric_type="weight", value_1=72.0, recorded_at=_today())
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["progress_percent"] == 40.0          # 2 / 5 = 40%
    assert item["remaining_value"] == 3
    assert item["remaining_text"] == "还差 3 kg"

    _add(client, user["header"], metric_type="weight", value_1=74.0, recorded_at=fmt(now_local()))
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 74.0             # 最近一条未软删体重记录
    assert item["progress_percent"] == 80.0


def test_g07_weight_current_uses_latest_active_record(client, user):
    """G-07：``weight`` 当前体重取**最近一条未软删**体重记录（软删记录不参与）。"""
    created_goal(create_goal(client, user["header"], goal_type="weight",
                             target_value=68.0, start_weight_kg=72.5))
    older = _add(client, user["header"], metric_type="weight", value_1=71.5,
                 recorded_at=fmt(dt_at(-2, 7, 0)))
    _add(client, user["header"], metric_type="weight", value_1=70.0, recorded_at=_today())
    assert client.delete(f"{API}/records/{older['id']}",
                         headers=user["header"]).status_code == 200
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 70.0


def test_g07_weight_without_data_returns_null(client, user):
    """G-07：``weight`` 无体重记录 / 无起始体重 → ``null``（**不补零、不估算**）。"""
    created_goal(create_goal(client, user["header"], goal_type="weight",
                             target_value=68.0, start_weight_kg=72.5))
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] is None
    assert item["progress_percent"] is None
    assert item["remaining_value"] is None
    assert item["remaining_text"] is None
    assert item["is_reached"] is False
    assert item["rate"] is None


def test_g07_weight_without_start_weight_returns_null(client, user):
    """G-07：``weight`` 起始体重为空（有体重记录）→ 完成度仍为 ``null``。"""
    created_goal(create_goal(client, user["header"], goal_type="weight", target_value=66.0))
    _add(client, user["header"], metric_type="weight", value_1=70.0, recorded_at=_today())
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 70.0
    assert item["progress_percent"] is None
    assert item["remaining_text"] is None


# ════════════════════════════════════════════════════════════════════
# sleep —— 当日派生时长
# ════════════════════════════════════════════════════════════════════
def test_g07_sleep_derived_duration(client, user):
    """G-07：``sleep`` 用 ``time_start → recorded_at`` 派生时长（复用第三批口径）。"""
    created_goal(create_goal(client, user["header"], goal_type="sleep", target_value=8))
    end = now_local().replace(microsecond=0)
    start = end - timedelta(hours=7, minutes=30)
    _add(client, user["header"], metric_type="sleep", value_1=4,
         time_start=fmt(start), recorded_at=fmt(end))

    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 7.5
    assert item["progress_percent"] == 93.8          # 7.5 / 8
    assert item["unit"] == "hour"
    assert item["period_label"] == "today"
    assert item["remaining_text"] == "还差 0.5 hour"


def test_g07_sleep_excludes_previous_day(client, user):
    """G-07：``sleep`` 按 ``recorded_at``（起床时间）归属当日。"""
    created_goal(create_goal(client, user["header"], goal_type="sleep", target_value=8))
    end = dt_at(-1, 7, 0)
    _add(client, user["header"], metric_type="sleep", value_1=4,
         time_start=fmt(end - timedelta(hours=8)), recorded_at=fmt(end))
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 0


# ════════════════════════════════════════════════════════════════════
# sport —— 本周
# ════════════════════════════════════════════════════════════════════
def test_g07_sport_weekly_count_and_min(client, user, peer):
    """G-07：``sport`` 本周聚合（``count`` 计次 / ``min`` 累计分钟）。"""
    min_goal = created_goal(create_goal(client, user["header"],
                                        goal_type="sport", target_value=150, attr_1="min"))
    _add(client, user["header"], metric_type="sport", value_1=30, attr_1="running",
         recorded_at=_today())
    _add(client, user["header"], metric_type="sport", value_1=20, attr_1="walking",
         recorded_at=fmt(now_local()))
    item = _progress(client, user["header"], goal_id=min_goal["id"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 50
    assert item["progress_percent"] == 33.3
    assert item["period_label"] == "this_week"
    assert item["remaining_text"] == "还差 100 min"

    count_goal = created_goal(create_goal(client, peer["header"],
                                          goal_type="sport", target_value=3, attr_1="count"))
    for _ in range(2):
        _add(client, peer["header"], metric_type="sport", value_1=30, attr_1="running",
             recorded_at=_today())
    other = _progress(client, peer["header"],
                      goal_id=count_goal["id"]).get_json()["data"]["items"][0]
    assert other["current_value"] == 2
    assert other["unit"] == "count"
    assert other["remaining_text"] == "还差 1 count"


def test_g07_sport_week_window_starts_monday(client, user):
    """G-07：``sport`` 周窗口 ``[周一00:00:00, 下周一00:00:00)`` —— 上周记录不计入。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="sport", target_value=150, attr_1="min"))
    last_week_day = week_start_offset() - 1          # 上周日（恒早于本周一）
    _add(client, user["header"], metric_type="sport", value_1=120, attr_1="running",
         recorded_at=fmt(dt_at(last_week_day, 10, 0)))
    item = _progress(client, user["header"], goal_id=goal["id"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 0

    _add(client, user["header"], metric_type="sport", value_1=120, attr_1="running",
         recorded_at=_today())
    item = _progress(client, user["header"], goal_id=goal["id"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 120
    assert item["progress_percent"] == 80.0


# ════════════════════════════════════════════════════════════════════
# rate —— 达标率窗口
# ════════════════════════════════════════════════════════════════════
def test_g07_rate_window_and_ratio(client, user):
    """G-07：``rate`` 只统计**有记录的天数**，缺失日期**不补零**。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=1000))
    _add(client, user["header"], metric_type="water", value_1=1200, recorded_at=_today())   # 达标
    _add(client, user["header"], metric_type="water", value_1=500,
         recorded_at=fmt(dt_at(-1, 9, 0)))                                                  # 未达标

    rate = _progress(client, user["header"]).get_json()["data"]["items"][0]["rate"]
    assert rate == {"window_days": 30, "days_recorded": 2, "days_reached": 1,
                    "reached_rate_percent": 50.0}


def test_g07_rate_window_seven_and_ninety(client, user):
    """G-07：``rate_window`` 支持 7 / 30 / 90；其他 → 400。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=1000))
    _add(client, user["header"], metric_type="water", value_1=1000, recorded_at=_today())

    seven = _progress(client, user["header"], rate_window=7).get_json()
    assert seven["data"]["items"][0]["rate"]["window_days"] == 7
    ninety = _progress(client, user["header"], rate_window=90).get_json()
    assert ninety["data"]["items"][0]["rate"]["window_days"] == 90

    for bad in ("45", "0", "-7", "abc"):
        resp = _progress(client, user["header"], rate_window=bad)
        assert resp.status_code == 400, bad
        assert resp.get_json()["code"] == "INVALID_PARAM"


def test_g07_rate_null_when_no_records(client, user):
    """G-07：``days_recorded = 0`` → ``reached_rate_percent`` 为 ``null``（不除零）。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=1000))
    rate = _progress(client, user["header"]).get_json()["data"]["items"][0]["rate"]
    assert rate == {"window_days": 30, "days_recorded": 0, "days_reached": 0,
                    "reached_rate_percent": None}


def test_g07_rate_window_excludes_older_days(client, user):
    """G-07：窗口外的旧记录不计入 ``days_recorded``（7 天窗口）。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=1000))
    _add(client, user["header"], metric_type="water", value_1=1000, recorded_at=_today())
    _add(client, user["header"], metric_type="water", value_1=1000,
         recorded_at=fmt(dt_at(-20, 9, 0)))          # 20 天前 → 7 天窗口外

    rate7 = _progress(client, user["header"], rate_window=7).get_json()["data"]["items"][0]["rate"]
    assert rate7["days_recorded"] == 1
    rate30 = _progress(client, user["header"], rate_window=30).get_json()["data"]["items"][0]["rate"]
    assert rate30["days_recorded"] == 2


def test_g07_rate_for_weekly_sport(client, user):
    """G-07：``sport``（weekly）也有 ``rate``：按"当日所属周"的周累计判定达标。"""
    created_goal(create_goal(client, user["header"],
                             goal_type="sport", target_value=100, attr_1="min"))
    today_is_recorded = _add(client, user["header"], metric_type="sport", value_1=100,
                             attr_1="running", recorded_at=_today())
    assert today_is_recorded["id"]

    rate = _progress(client, user["header"]).get_json()["data"]["items"][0]["rate"]
    assert rate["days_recorded"] == 1
    assert rate["days_reached"] == 1
    assert rate["reached_rate_percent"] == 100.0


# ════════════════════════════════════════════════════════════════════
# 状态与隔离
# ════════════════════════════════════════════════════════════════════
def test_g07_paused_goal_still_returns_full_progress(client, user):
    """G-07（D-G3）：暂停目标**仍返回完整完成度**，仅以 ``status`` 区分。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    _add(client, user["header"], metric_type="water", value_1=1500, recorded_at=_today())
    assert client.post(f"{API}/goals/{goal['id']}/pause",
                       headers=user["header"]).status_code == 200

    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["status"] == 0
    assert item["current_value"] == 1500
    assert item["progress_percent"] == 75.0
    assert item["remaining_text"] == "还差 500 ml"
    assert item["rate"]["days_recorded"] == 1


def test_g07_soft_deleted_goal_not_returned(client, user):
    """G-07：已软删目标不出现在完成度列表。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    client.delete(f"{API}/goals/{goal['id']}", headers=user["header"])
    assert _progress(client, user["header"]).get_json()["data"]["items"] == []


def test_g07_goal_id_cross_user_and_invalid(client, user, peer):
    """G-07：``goal_id`` 跨用户 / 不存在 → 404；非法 ``goal_id`` → 400。"""
    theirs = created_goal(create_goal(client, peer["header"],
                                      goal_type="water", target_value=2000))
    cross = _progress(client, user["header"], goal_id=theirs["id"])
    assert cross.status_code == 404
    assert cross.get_json()["code"] == "RESOURCE_NOT_FOUND"
    assert _progress(client, user["header"], goal_id=99999999).status_code == 404
    assert _progress(client, user["header"], goal_id="abc").status_code == 400


def test_g07_sports_aggregation_is_user_scoped(client, user, peer):
    """G-07：``health_record`` 聚合**必须带 user_id**（跨用户零泄露）。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=2000))
    _add(client, peer["header"], metric_type="water", value_1=2000, recorded_at=_today())
    item = _progress(client, user["header"]).get_json()["data"]["items"][0]
    assert item["current_value"] == 0
    assert item["remaining_text"] == "还差 2000 ml"


def test_g07_requires_auth(client):
    """G-07：未认证 → 401；``user_id`` 注入 → 400。"""
    assert client.get(f"{API}/goals/progress").status_code == 401


def test_g07_client_user_id_rejected(client, user):
    """G-07：query ``user_id`` → 400。"""
    resp = client.get(f"{API}/goals/progress?user_id=1", headers=user["header"])
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "INVALID_PARAM"
