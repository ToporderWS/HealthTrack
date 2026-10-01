# -*- coding: utf-8 -*-
"""S2 第五批 —— 统一响应四字段 / 身份隔离 / 聚合隔离 契约测试。

依据：
- 《S1-B 第二批 API 接口设计文档》§3.4 / §3.5（统一响应四字段）
- 同文档 13.1 第 7 条「聚合隔离」：趋势 / 摘要 / 首页的聚合**一律限定 ``user_id``**
  且叠加 ``is_deleted=0``（**最易遗漏点，S2 评审必查**）
- 《S1-D 技术方案最终冻结》§6.3：``user_id`` **只能由服务端从 Token 解析**
"""
from __future__ import annotations

import re

from tests.batch5.conftest import (
    add_record,
    create_goal,
    dt_at,
    fmt,
    overview,
    payload_of,
    summary,
    trend,
)

API = "/api/v1"
HEX32 = re.compile(r"^[0-9a-f]{32}$")

ENDPOINTS = (
    ("/api/v1/home/overview", {}),
    ("/api/v1/stats/trend", {"metric_type": "water"}),
    ("/api/v1/stats/summary", {"metric_type": "water"}),
)


# ════════════════════════════════════════════════════════════════════
# 统一响应四字段
# ════════════════════════════════════════════════════════════════════
def test_envelope_four_fields(client, user):
    """三接口：成功响应恰为 ``{code, message, data, request_id}`` 四字段。"""
    for path, query in ENDPOINTS:
        resp = client.get(path, headers=user["header"], query_string=query)
        assert resp.status_code == 200, (path, resp.get_json())
        assert resp.is_json, path
        body = resp.get_json()
        assert set(body) == {"code", "message", "data", "request_id"}, (path, body)
        assert body["code"] == "OK"
        assert body["message"] == "成功"
        assert HEX32.match(body["request_id"]), body["request_id"]
        assert resp.headers.get("X-Request-Id") == body["request_id"], path


def test_error_envelope_is_four_fields(client, user):
    """三接口：错误响应为四字段（无字段级明细时不追加 ``errors``）。"""
    for path, _query in ENDPOINTS:
        resp = client.get(path)                     # 无 Token
        assert resp.status_code == 401, path
        body = resp.get_json()
        assert set(body) == {"code", "message", "data", "request_id"}, (path, body)
        assert body["code"] == "UNAUTHENTICATED"
        assert body["data"] is None
        assert HEX32.match(body["request_id"])


def test_all_endpoints_require_auth(client):
    """三接口（含无效 Token）均 → 401。"""
    for path, query in ENDPOINTS:
        assert client.get(path, query_string=query).status_code == 401, path
        bad = client.get(path, headers={"Authorization": "Bearer not-a-real-token"},
                         query_string=query)
        assert bad.status_code == 401, path
        assert bad.get_json()["code"] == "UNAUTHENTICATED", path


def test_no_pagination_total_key(client, user):
    """三接口**均不分页**：响应中不出现 ``total`` / ``next_cursor``。"""
    add_record(client, user["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    for path, query in ENDPOINTS:
        data = payload_of(client.get(path, headers=user["header"], query_string=query))
        assert "total" not in data, path
        assert "next_cursor" not in data, path


# ════════════════════════════════════════════════════════════════════
# 身份隔离（user_id 只能来自 Token）
# ════════════════════════════════════════════════════════════════════
def test_user_id_in_query_rejected(client, user):
    """三接口：query 携带 ``user_id`` → 400 ``INVALID_PARAM``（全局守卫）。"""
    for path, query in ENDPOINTS:
        merged = dict(query)
        merged["user_id"] = user["user_id"]
        resp = client.get(path, headers=user["header"], query_string=merged)
        assert resp.status_code == 400, (path, resp.get_json())
        assert resp.get_json()["code"] == "INVALID_PARAM", path


def test_user_id_in_body_rejected(client, user):
    """三接口：JSON 体携带 ``user_id`` → 400 ``INVALID_PARAM``（全局守卫）。"""
    for path, query in ENDPOINTS:
        resp = client.get(path, headers=user["header"], query_string=query,
                          json={"user_id": user["user_id"]})
        assert resp.status_code == 400, (path, resp.get_json())
        assert resp.get_json()["code"] == "INVALID_PARAM", path


def test_other_user_id_cannot_read_foreign_data(client, user, peer):
    """三接口：伪造对端 ``user_id`` **不能**读到对端数据（仍 400 拦截）。"""
    add_record(client, peer["header"], metric_type="water", value_1=1500,
               recorded_at=fmt(dt_at(-1, 9, 0)))
    create_goal(client, peer["header"], goal_type="water", target_value=2000)

    for path, query in ENDPOINTS:
        merged = dict(query)
        merged["user_id"] = peer["user_id"]
        assert client.get(path, headers=user["header"],
                          query_string=merged).status_code == 400, path

    # 正常调用：本端看不到对端任何数据
    assert payload_of(overview(client, user["header"]))["today"]["record_count"] == 0
    assert payload_of(trend(client, user["header"], metric_type="water"))["points"] == []
    assert payload_of(summary(client, user["header"],
                              metric_type="water"))["summary"]["recorded_days"]["recorded"] == 0


# ════════════════════════════════════════════════════════════════════
# 聚合隔离（user_id + is_deleted=0 同时生效）
# ════════════════════════════════════════════════════════════════════
def test_aggregations_scoped_to_owner_and_soft_delete(client, user, peer):
    """三接口：聚合同时受 ``user_id`` 与 ``is_deleted=0`` 约束（互不串号）。"""
    mine_keep = add_record(client, user["header"], metric_type="water", value_1=1000,
                           recorded_at=fmt(dt_at(-1, 8, 0)))
    mine_drop = add_record(client, user["header"], metric_type="water", value_1=1000,
                           recorded_at=fmt(dt_at(-1, 9, 0)))
    add_record(client, peer["header"], metric_type="water", value_1=1000,
               recorded_at=fmt(dt_at(-1, 10, 0)))

    assert client.delete(f"{API}/records/{mine_drop['record']['id']}",
                         headers=user["header"]).status_code == 200

    trend_data = payload_of(trend(client, user["header"], metric_type="water", window=7))
    assert trend_data["points"] == [{"date": dt_at(-1, 8, 0).date().isoformat(),
                                     "total_ml": 1000}]
    summary_body = payload_of(summary(client, user["header"], metric_type="water",
                                      window=7))["summary"]
    assert summary_body["average"] == 1000
    assert summary_body["recorded_days"]["recorded"] == 1

    overview_data = payload_of(overview(client, user["header"]))
    own_ids = {r["id"] for r in overview_data["recent_records"]}
    assert own_ids == {mine_keep["record"]["id"]}


def test_peer_data_never_leaks_into_own_payload(client, user, peer):
    """三接口：对端两日均数据 + 目标 → 本端三接口均为空态。"""
    for offset in (-2, -1):
        add_record(client, peer["header"], metric_type="weight", value_1=90.0,
                   recorded_at=fmt(dt_at(offset, 9, 0)))
    create_goal(client, peer["header"], goal_type="weight", target_value=60.0,
                start_weight_kg=90.0)

    assert payload_of(overview(client, user["header"]))["recent_records"] == []
    assert payload_of(overview(client, user["header"]))["goals"] == []
    assert payload_of(trend(client, user["header"], metric_type="weight"))["points"] == []
    assert payload_of(summary(client, user["header"],
                              metric_type="weight"))["summary"]["max"] is None
