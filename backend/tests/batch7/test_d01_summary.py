# -*- coding: utf-8 -*-
"""S2 第七批 D-01（``GET /api/v1/me/data/summary``）验收用例。

覆盖：鉴权 / 用户隔离 / 空数据 / 8 类指标**固定顺序** / 只返回有数据指标 /
``is_deleted`` 排除 / ``total_records`` / ``count`` / ``first·last recorded_at`` /
``goals`` 在用与暂停 / ``profile`` 6 字段填写数 / 禁止越权参数 / 不含数值统计。
"""
from __future__ import annotations

import re

from app.services.metric_rules import METRIC_TYPES
from tests.batch7.conftest import (
    add_goal,
    add_record,
    payload_of,
    summary,
    ts_before,
)

SUMMARY_KEYS = {"total_records", "by_metric", "goals", "profile"}
ITEM_KEYS = {"metric_type", "count", "first_recorded_at", "last_recorded_at"}
GOAL_KEYS = {"active_count", "paused_count"}
PROFILE_KEYS = {"health_fields_filled", "health_fields_total"}

#: 数值统计类键名（D-01 **不得**返回任何数值统计，属趋势页 S-03）
STAT_KEYS = {"avg", "average", "mean", "min", "max", "sum", "total", "latest", "value",
             "value_1", "highest", "lowest", "trend", "chart", "points"}

DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _summary(client, header):
    return payload_of(summary(client, header))


def _seed_all_eight(client, header) -> None:
    """逆 ``METRIC_TYPES`` 顺序写入 8 类指标各 1 条（用于验证输出顺序**不随写入顺序**）。"""
    add_record(client, header, metric_type="mood", value_1=4,
               recorded_at=ts_before(days=1))
    add_record(client, header, metric_type="sport", value_1=30, attr_1="running",
               recorded_at=ts_before(days=1))
    add_record(client, header, metric_type="water", value_1=500,
               recorded_at=ts_before(days=1))
    add_record(client, header, metric_type="sleep", value_1=4,
               time_start=ts_before(days=1, hours=8), recorded_at=ts_before(days=1, hours=1))
    add_record(client, header, metric_type="glucose", value_1="5.6", attr_1="fasting",
               recorded_at=ts_before(days=1))
    add_record(client, header, metric_type="heart", value_1=72,
               recorded_at=ts_before(days=1))
    add_record(client, header, metric_type="bp", value_1=120, value_2=80,
               recorded_at=ts_before(days=1))
    add_record(client, header, metric_type="weight", value_1="70.50",
               recorded_at=ts_before(days=1))


# ════════════════════════════════════════════════════════════════════
# 鉴权 / 隔离
# ════════════════════════════════════════════════════════════════════
def test_d01_requires_auth(client):
    """无 Token → ``401 UNAUTHENTICATED``。"""
    resp = client.get("/api/v1/me/data/summary")
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_d01_bad_token(client, user):
    """坏 Token → ``401``。"""
    resp = summary(client, {"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_d01_rejects_user_id_in_query(client, user, peer):
    """query 携带 ``user_id`` → ``400 INVALID_PARAM``（user_id 只能来自 Token）。"""
    resp = client.get(f"/api/v1/me/data/summary?user_id={peer['user_id']}",
                      headers=user["header"])
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"


def test_d01_isolation_between_users(client, rich_user, peer):
    """U：只统计**本人**数据；对端空数据（不受本端影响）。"""
    mine = _summary(client, rich_user["header"])
    other = _summary(client, peer["header"])

    assert mine["total_records"] == 3
    assert other["total_records"] == 0
    assert other["by_metric"] == []
    assert other["goals"] == {"active_count": 0, "paused_count": 0}


# ════════════════════════════════════════════════════════════════════
# 空数据 / 结构
# ════════════════════════════════════════════════════════════════════
def test_d01_empty_payload_exact(client, user):
    """空数据：``total_records=0`` + ``by_metric=[]``（**不逐类返回 0 行**）。"""
    data = _summary(client, user["header"])
    assert data == {
        "total_records": 0,
        "by_metric": [],
        "goals": {"active_count": 0, "paused_count": 0},
        "profile": {"health_fields_filled": 0, "health_fields_total": 6},
    }


def test_d01_top_level_keys(client, rich_user):
    """顶层恰为冻结 4 键。"""
    data = _summary(client, rich_user["header"])
    assert set(data.keys()) == SUMMARY_KEYS, data
    assert set(data["goals"].keys()) == GOAL_KEYS
    assert set(data["profile"].keys()) == PROFILE_KEYS


def test_d01_item_shape_and_time_format(client, rich_user):
    """``by_metric`` 每项**恰 4 键**；时间形如 ``YYYY-MM-DD HH:mm:ss``（无时区后缀）。"""
    data = _summary(client, rich_user["header"])
    assert data["by_metric"], data
    for item in data["by_metric"]:
        assert set(item.keys()) == ITEM_KEYS, item
        assert isinstance(item["count"], int) and item["count"] > 0
        assert DT_RE.match(item["first_recorded_at"]), item
        assert DT_RE.match(item["last_recorded_at"]), item


def test_d01_no_numeric_stats_anywhere(client, rich_user):
    """**不得**返回任何数值统计（数值统计属趋势页 S-03）。"""
    data = _summary(client, rich_user["header"])
    flat = set(data.keys()) | set(data["goals"].keys()) | set(data["profile"].keys())
    for item in data["by_metric"]:
        flat |= set(item.keys())
    assert not (flat & STAT_KEYS), sorted(flat & STAT_KEYS)
    for item in data["by_metric"]:
        assert "value" not in item and "avg" not in item


# ════════════════════════════════════════════════════════════════════
# 指标顺序 / 计数 / 时间范围
# ════════════════════════════════════════════════════════════════════
def test_d01_metric_order_is_frozen(client, user):
    """8 类指标按 ``METRIC_TYPES`` **固定顺序**输出（与写入顺序无关）。"""
    _seed_all_eight(client, user["header"])
    data = _summary(client, user["header"])

    assert [i["metric_type"] for i in data["by_metric"]] == list(METRIC_TYPES)
    assert data["total_records"] == 8
    assert all(i["count"] == 1 for i in data["by_metric"])


def test_d01_only_metrics_with_data(client, rich_user):
    """只返回**有数据**的指标（rich_user 3 类）。"""
    data = _summary(client, rich_user["header"])
    assert [i["metric_type"] for i in data["by_metric"]] == ["weight", "water", "mood"]


def test_d01_counts_and_total(client, rich_user):
    """``count`` = 该指标活跃条数；``total_records`` = 各 count 之和。"""
    data = _summary(client, rich_user["header"])
    counts = {i["metric_type"]: i["count"] for i in data["by_metric"]}
    assert counts == {"weight": 1, "water": 1, "mood": 1}
    assert data["total_records"] == sum(counts.values()) == 3


def test_d01_excludes_soft_deleted_records(client, rich_user):
    """F：软删记录**不计入**（rich_user 的 heart 记录已软删）。"""
    types = [i["metric_type"] for i in _summary(client, rich_user["header"])["by_metric"]]
    assert "heart" not in types
    assert rich_user["dropped_record_id"] > 0


def test_d01_soft_delete_lowers_counts(client, user):
    """软删一条后 ``count`` 与 ``total_records`` 同步下降。"""
    t_keep = ts_before(days=2)
    add_record(client, user["header"], metric_type="water", value_1=200, recorded_at=t_keep)
    gone = add_record(client, user["header"], metric_type="water", value_1=300,
                      recorded_at=ts_before(days=1))

    before = _summary(client, user["header"])
    assert before["total_records"] == 2
    assert before["by_metric"][0]["count"] == 2

    resp = client.delete(f"/api/v1/records/{int(gone['id'])}", headers=user["header"])
    assert resp.status_code == 200, resp.get_json()

    after = _summary(client, user["header"])
    assert after["total_records"] == 1
    assert after["by_metric"][0]["count"] == 1
    # 仍保留的那条（更早的记录）成为唯一 first/last
    assert after["by_metric"][0]["first_recorded_at"] == t_keep
    assert after["by_metric"][0]["last_recorded_at"] == t_keep


def test_d01_first_last_recorded_at(client, user):
    """``first_recorded_at`` / ``last_recorded_at`` = 该指标活跃记录的最早 / 最晚发生时间。

    ★ 时间戳**必须先算好再用**：``ts_before()`` 基于"当前时刻"计算，
    在写入与断言两处分别调用会跨越秒边界（flaky）。
    """
    t_old = ts_before(days=5)
    t_mid = ts_before(days=3)
    t_new = ts_before(days=1)
    add_record(client, user["header"], metric_type="water", value_1=100, recorded_at=t_old)
    add_record(client, user["header"], metric_type="water", value_1=200, recorded_at=t_mid)
    add_record(client, user["header"], metric_type="water", value_1=300, recorded_at=t_new)

    item = _summary(client, user["header"])["by_metric"][0]
    assert item["metric_type"] == "water"
    assert item["count"] == 3
    assert item["first_recorded_at"] == t_old
    assert item["last_recorded_at"] == t_new


def test_d01_same_day_boundary_stability(client, user):
    """同一指标不同时间均被纳入（半开区间口径不影响 D-01 全量统计）。"""
    add_record(client, user["header"], metric_type="mood", value_1=3,
               recorded_at=ts_before(days=2))
    add_record(client, user["header"], metric_type="mood", value_1=5,
               recorded_at=ts_before(hours=1))
    item = _summary(client, user["header"])["by_metric"][0]
    assert item["count"] == 2
    assert item["first_recorded_at"] < item["last_recorded_at"]


# ════════════════════════════════════════════════════════════════════
# goals / profile
# ════════════════════════════════════════════════════════════════════
def test_d01_goals_active_and_paused(client, rich_user):
    """``goals`` = 在用 1 / 暂停 1（rich_user：water 在用 + sport 暂停）。"""
    assert _summary(client, rich_user["header"])["goals"] == {
        "active_count": 1, "paused_count": 1,
    }


def test_d01_goals_exclude_soft_deleted(client, user):
    """软删目标**不计入**（直插一条已软删目标）。"""
    add_goal(user["user_id"], goal_type="water", status=1)
    add_goal(user["user_id"], goal_type="sleep", status=1, is_deleted=1,
             deleted_marker=99999)
    assert _summary(client, user["header"])["goals"] == {
        "active_count": 1, "paused_count": 0,
    }


def test_d01_goals_reflect_status_change(client, user):
    """目标在用/暂停状态变化在 D-01 立即可见。"""
    goal_id = add_goal(user["user_id"], goal_type="water", status=1)
    assert _summary(client, user["header"])["goals"]["active_count"] == 1

    resp = client.post(f"/api/v1/goals/{goal_id}/pause", headers=user["header"])
    assert resp.status_code == 200, resp.get_json()

    goals = _summary(client, user["header"])["goals"]
    assert goals == {"active_count": 0, "paused_count": 1}


def test_d01_profile_filled_and_total(client, rich_user):
    """``profile`` = 6 个健康字段中非 NULL 的个数；``health_fields_total`` 恒为 6。"""
    profile = _summary(client, rich_user["header"])["profile"]
    assert profile == {"health_fields_filled": 3, "health_fields_total": 6}


def test_d01_profile_without_row(client, user):
    """未建档（无 ``user_profile`` 行）→ ``filled = 0``（**不是 404**）。"""
    assert _summary(client, user["header"])["profile"] == {
        "health_fields_filled": 0, "health_fields_total": 6,
    }


def test_d01_profile_counts_only_health_fields(client, user):
    """昵称 / 性别 / 出生日期**不计入** 6 个健康字段。"""
    from tests.batch7.conftest import fill_profile

    fill_profile(user["user_id"], keep=True)
    assert _summary(client, user["header"])["profile"]["health_fields_filled"] == 0

    fill_profile(user["user_id"], keep=True, height_cm="170.0")
    assert _summary(client, user["header"])["profile"]["health_fields_filled"] == 1


# ════════════════════════════════════════════════════════════════════
# 幂等 / envelope
# ════════════════════════════════════════════════════════════════════
def test_d01_get_is_idempotent(client, rich_user):
    """GET 幂等：连续两次结果完全一致（不改变任何状态）。"""
    first = _summary(client, rich_user["header"])
    second = _summary(client, rich_user["header"])
    assert first == second


def test_d01_envelope_and_request_id(client, user):
    """统一 envelope：``code/message/data/request_id`` + ``X-Request-Id`` 响应头。"""
    resp = summary(client, user["header"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "request_id"}
    assert body["code"] == "OK"
    assert body["message"] == "成功"
    assert resp.headers.get("X-Request-Id") == body["request_id"]
