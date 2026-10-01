# -*- coding: utf-8 -*-
"""S-01 ``GET /api/v1/home/overview`` —— 首页概览契约测试。

依据：《S1-B 第二批 API 接口设计文档》§九「S-01 首页概览」
"""
from __future__ import annotations

from datetime import timedelta

from app.core.security import now_local

from tests.batch5.conftest import (
    add_record,
    create_goal,
    created_goal,
    day_str,
    dt_at,
    fmt,
    overview,
    payload_of,
)

API = "/api/v1"
TODAY = day_str(0)


def _now() -> str:
    return fmt(now_local())


def test_s01_requires_auth(client):
    """S-01：缺 Token → 401 ``UNAUTHENTICATED``。"""
    resp = client.get(f"{API}/home/overview")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_s01_empty_state(client, user):
    """S-01：无任何数据 → 空态但 **200**（空态由客户端渲染，服务端不返文案）。"""
    data = payload_of(overview(client, user["header"]))
    assert set(data) == {"date", "today", "goals", "recent_records", "reminder_fallback"}
    assert data["date"] == TODAY
    assert data["today"] == {"record_count": 0, "metric_types_recorded": []}
    assert data["goals"] == []
    assert data["recent_records"] == []
    assert data["reminder_fallback"] == {
        "source": "local",
        "note": "N/A（提醒兜底计数由客户端本地计算，服务端不提供）",
    }


def test_s01_today_counts_only_today_and_orders_metric_types(client, user):
    """S-01：今日记录数只统计今日；``metric_types_recorded`` 按 METRIC_TYPES 固定顺序。"""
    for metric, payload in (
        ("mood", {"metric_type": "mood", "value_1": 4, "recorded_at": _now()}),
        ("water", {"metric_type": "water", "value_1": 1500, "recorded_at": _now()}),
        ("weight", {"metric_type": "weight", "value_1": 70.5, "recorded_at": _now()}),
    ):
        add_record(client, user["header"], **payload)
    # 昨日记录 → 不计入今日
    add_record(client, user["header"], metric_type="weight", value_1=71.0,
               recorded_at=fmt(dt_at(-1, 9, 0)))

    data = payload_of(overview(client, user["header"]))
    assert data["today"]["record_count"] == 3
    assert data["today"]["metric_types_recorded"] == ["weight", "water", "mood"]
    # 最近记录包含今日 3 条 + 昨日 1 条
    assert len(data["recent_records"]) == 4
    assert data["recent_records"][0]["recorded_at"].startswith(TODAY)


def test_s01_recent_records_fixed_ten_desc(client, user):
    """S-01：``recent_records`` 固定 **10 条**，``recorded_at DESC, id DESC``。"""
    for offset in range(-12, 0):  # 12 条历史记录（均为过去日，无未来）
        add_record(client, user["header"], metric_type="water", value_1=200,
                   recorded_at=fmt(dt_at(offset, 9, 0)))

    data = payload_of(overview(client, user["header"]))
    records = data["recent_records"]
    assert len(records) == 10
    stamps = [r["recorded_at"] for r in records]
    assert stamps == sorted(stamps, reverse=True)
    assert stamps[0].startswith(day_str(-1))
    assert stamps[-1].startswith(day_str(-10))
    assert set(records[0]) == {
        "id", "metric_type", "value_1", "unit", "recorded_at",
        "time_start", "note", "tags",
    }
    assert records[0]["unit"] == "ml"


def test_s01_recent_records_include_tags_and_sleep_fields(client, user):
    """S-01：``tags`` 来自 ``record_tag``；``time_start`` 仅睡眠有值。"""
    add_record(client, user["header"], metric_type="mood", value_1=4,
               tags=["tired", "relaxed"], note="备注", recorded_at=_now())
    add_record(client, user["header"], metric_type="sleep", value_1=5,
               time_start=fmt(now_local() - timedelta(hours=8)), recorded_at=_now())

    records = payload_of(overview(client, user["header"]))["recent_records"]
    mood = next(r for r in records if r["metric_type"] == "mood")
    sleep = next(r for r in records if r["metric_type"] == "sleep")
    assert mood["tags"] == ["tired", "relaxed"]
    assert mood["note"] == "备注"
    assert sleep["time_start"] is not None
    assert sleep["unit"] == "score"


def test_s01_goals_reuse_g07_and_expose_exactly_eight_fields(client, user):
    """S-01：``goals[]`` **只读复用 G-07**，仅 8 个字段；1500/2000 → 75.0。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=2000))
    add_record(client, user["header"], metric_type="water", value_1=1500,
               recorded_at=fmt(dt_at(0, 1, 0)))

    goals = payload_of(overview(client, user["header"]))["goals"]
    assert len(goals) == 1
    goal = goals[0]
    assert set(goal) == {
        "goal_id", "goal_type", "target_value", "current_value", "unit",
        "progress_percent", "is_reached", "remaining_text",
    }
    assert goal["goal_type"] == "water"
    assert goal["target_value"] == 2000
    assert goal["unit"] == "ml"
    assert goal["current_value"] == 1500
    assert goal["progress_percent"] == 75.0
    assert goal["is_reached"] is False
    assert goal["remaining_text"] == "还差 500 ml"


def test_s01_goals_include_paused_and_ordered_by_type_then_id(client, user):
    """S-01：``goals[]`` 含**暂停**目标（T-3），顺序 ``goal_type ASC, id ASC``。"""
    sleep_goal = created_goal(create_goal(client, user["header"],
                                         goal_type="sleep", target_value=8))
    water_goal = created_goal(create_goal(client, user["header"],
                                         goal_type="water", target_value=2000))
    assert client.post(
        f"{API}/goals/{water_goal['id']}/pause", headers=user["header"]
    ).status_code == 200

    goals = payload_of(overview(client, user["header"]))["goals"]
    assert [g["goal_type"] for g in goals] == ["sleep", "water"]  # sleep < water
    assert {g["goal_id"] for g in goals} == {sleep_goal["id"], water_goal["id"]}


def test_s01_soft_deleted_record_excluded(client, user):
    """S-01：软删记录**不计入**今日统计与最近记录。"""
    created = add_record(client, user["header"], metric_type="water", value_1=1500,
                         recorded_at=_now())
    assert payload_of(overview(client, user["header"]))["today"]["record_count"] == 1

    deleted = client.delete(f"{API}/records/{created['record']['id']}",
                            headers=user["header"])
    assert deleted.status_code == 200, deleted.get_json()

    data = payload_of(overview(client, user["header"]))
    assert data["today"]["record_count"] == 0
    assert data["recent_records"] == []


def test_s01_user_isolation(client, user, peer):
    """S-01：跨用户**零泄漏**（对端数据不出现在本端概览）。"""
    add_record(client, peer["header"], metric_type="water", value_1=1500,
               recorded_at=_now())
    created_goal(create_goal(client, peer["header"], goal_type="water", target_value=2000))

    data = payload_of(overview(client, user["header"]))
    assert data["today"]["record_count"] == 0
    assert data["recent_records"] == []
    assert data["goals"] == []


def test_s01_invalid_tz_offset_returns_400(client, user):
    """S-01：``tz_offset_minutes`` 非整数 → 400 ``INVALID_PARAM``（仅校验不偏移）。"""
    resp = overview(client, user["header"], tz_offset_minutes="abc")
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "INVALID_PARAM"


def test_s01_accepts_valid_tz_offset(client, user):
    """S-01：合法 ``tz_offset_minutes`` 被接受，且**不改变** ``date``（T-2 不偏移）。"""
    data = payload_of(overview(client, user["header"], tz_offset_minutes="480"))
    assert data["date"] == TODAY


def test_s01_date_reflects_current_local_day(client, user):
    """S-01：``date`` 为**用户当前日**（服务器本地日，D-4 单一时区）。"""
    from app.core.security import now_local

    assert payload_of(overview(client, user["header"]))["date"] == now_local().date().isoformat()
