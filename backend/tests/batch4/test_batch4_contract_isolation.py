# -*- coding: utf-8 -*-
"""S2 第四批 L/P/Q/R/S（认证守卫 / 响应契约 / 隔离 / 残留检查）。

覆盖验收项：
- L：G-01~G-07 全部接口必须认证（免 Token → 401）
- P/Q：统一响应契约 ``{code,message,data,request_id}`` + 32 位 ``request_id``
  且与 ``X-Request-Id`` 一致
- R/S：客户端 ``user_id`` 一律 400；跨用户零泄露；软删不可见
- DB residual：测试结束后 8 张业务表**非测试数据 0 行**、``health_goal`` 无残留
"""
from __future__ import annotations

import re

from tests.batch4.conftest import (
    API,
    BUSINESS_TABLES,
    business_row_counts,
    create_goal,
    created_goal,
    non_test_row_counts,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")

#: G 全部接口：(method, path)
ENDPOINTS = (
    ("GET", "/goals"),
    ("POST", "/goals"),
    ("GET", "/goals/progress"),
    ("PATCH", "/goals/1"),
    ("DELETE", "/goals/1"),
    ("POST", "/goals/1/pause"),
    ("POST", "/goals/1/resume"),
)


def _assert_contract(resp, *, allow_errors=False):
    body = resp.get_json()
    assert body is not None, resp.status_code
    keys = set(body.keys())
    assert {"code", "message", "data", "request_id"} <= keys
    assert keys <= {"code", "message", "data", "request_id", "errors"}
    if not allow_errors:
        assert "errors" not in keys
    assert HEX32.match(body["request_id"]), body["request_id"]
    assert resp.headers["X-Request-Id"] == body["request_id"]
    return body


# ════════════════════════════════════════════════════════════════════
# L —— 认证守卫
# ════════════════════════════════════════════════════════════════════
def test_l_all_endpoints_require_auth(client):
    """L：G 全部接口免 Token → 401（不泄露任何业务信息）。"""
    for method, path in ENDPOINTS:
        kwargs = {"json": {}} if method in ("POST", "PATCH") else {}
        resp = getattr(client, method.lower())(f"{API}{path}", **kwargs)
        assert resp.status_code == 401, (method, path, resp.status_code)
        body = resp.get_json()
        assert body["code"] == "UNAUTHENTICATED"
        assert body["data"] is None


def test_l_invalid_token_rejected(client):
    """L：伪造 / 畸形 Token → 401。"""
    for header in ({"Authorization": "Bearer not-a-jwt"},
                   {"Authorization": "Basic abc"},
                   {"Authorization": "Bearer "}):
        assert client.get(f"{API}/goals", headers=header).status_code == 401


# ════════════════════════════════════════════════════════════════════
# P / Q —— 响应契约
# ════════════════════════════════════════════════════════════════════
def test_pq_success_contract_on_every_endpoint(client, user):
    """P/Q：G 全部接口的成功响应均满足四键 + ``request_id`` 契约。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    gid = goal["id"]

    calls = {
        ("GET", "/goals"): client.get(f"{API}/goals", headers=user["header"]),
        ("GET", "/goals/progress"): client.get(f"{API}/goals/progress", headers=user["header"]),
        ("POST", "/goals"): create_goal(client, user["header"],
                                        goal_type="sleep", target_value=8),
        ("PATCH", "/goals/1"): client.patch(f"{API}/goals/{gid}", headers=user["header"],
                                            json={"target_value": 2500}),
        ("POST", "/goals/1/pause"): client.post(f"{API}/goals/{gid}/pause",
                                                headers=user["header"]),
        ("POST", "/goals/1/resume"): client.post(f"{API}/goals/{gid}/resume",
                                                 headers=user["header"]),
        ("DELETE", "/goals/1"): client.delete(f"{API}/goals/{gid}", headers=user["header"]),
    }
    for (method, path), resp in calls.items():
        assert resp.status_code in (200, 201), (method, path, resp.get_json())
        body = _assert_contract(resp)
        assert body["code"] == "OK", (method, path, body)


def test_pq_failure_contract_carries_errors_only_when_field_level(client, user):
    """P/Q：失败响应四键齐全；``errors[]`` 仅在字段级明细存在时出现。"""
    missing = create_goal(client, user["header"], target_value=2000)          # 缺 goal_type → 400
    assert missing.status_code == 400
    body = _assert_contract(missing, allow_errors=True)
    assert body["code"] == "INVALID_PARAM"
    assert body["errors"] and body["errors"][0]["code"] == "REQUIRED"

    not_found = client.delete(f"{API}/goals/99999999", headers=user["header"])
    assert not_found.status_code == 404
    body = _assert_contract(not_found)
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert body["data"] is None

    hard = create_goal(client, user["header"], goal_type="water", target_value=30000)
    assert hard.status_code == 422
    body = _assert_contract(hard, allow_errors=True)
    assert body["code"] == "VALIDATION_FAILED"

    conflict = create_goal(client, user["header"], goal_type="water", target_value=1000)
    assert conflict.status_code == 201
    dup = create_goal(client, user["header"], goal_type="water", target_value=1500)
    assert dup.status_code == 409
    body = _assert_contract(dup)                       # 409 不带字段级明细
    assert body["code"] == "GOAL_TYPE_EXISTS"

    soft = create_goal(client, user["header"], goal_type="sleep", target_value=20)
    assert soft.status_code == 200
    body = _assert_contract(soft)                      # 软提示**不带** errors[]
    assert body["code"] == "SOFT_WARNING"
    assert body["data"]["requires_confirm"] is True


def test_pq_request_id_unique_per_request(client, user):
    """Q：``request_id`` 每请求唯一。"""
    ids = set()
    for _ in range(6):
        body = client.get(f"{API}/goals", headers=user["header"]).get_json()
        ids.add(body["request_id"])
    assert len(ids) == 6


# ════════════════════════════════════════════════════════════════════
# R —— 客户端 user_id
# ════════════════════════════════════════════════════════════════════
def test_r_client_user_id_in_query_rejected(client, user):
    """R：G 全部接口带 query ``user_id`` → 400。"""
    for method, path in ENDPOINTS:
        kwargs = {"json": {}} if method in ("POST", "PATCH") else {}
        resp = getattr(client, method.lower())(f"{API}{path}?user_id=1",
                                               headers=user["header"], **kwargs)
        assert resp.status_code == 400, (method, path, resp.status_code)
        assert resp.get_json()["code"] == "INVALID_PARAM"


def test_r_client_user_id_in_body_rejected(client, user):
    """R：G 写类接口带请求体 ``user_id`` → 400 且不产生任何写入。"""
    targets = (("POST", "/goals"), ("PATCH", "/goals/1"))
    for method, path in targets:
        resp = getattr(client, method.lower())(f"{API}{path}", headers=user["header"],
                                               json={"user_id": 1})
        assert resp.status_code == 400, (method, path, resp.status_code)
        assert resp.get_json()["code"] == "INVALID_PARAM"
    assert client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"] == []


# ════════════════════════════════════════════════════════════════════
# S —— 跨用户隔离
# ════════════════════════════════════════════════════════════════════
def test_s_cross_user_isolation_summary(client, user, peer):
    """S：跨用户全链路隔离（G-01 ~ G-07）。"""
    mine = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    theirs = created_goal(create_goal(client, peer["header"],
                                      goal_type="water", target_value=3000))

    assert client.patch(f"{API}/goals/99999999", headers=user["header"],
                        json={"target_value": 1}).status_code == 404
    assert client.get(f"{API}/goals/progress?goal_id=" + str(theirs["id"]),
                      headers=user["header"]).status_code == 404
    assert client.patch(f"{API}/goals/{theirs['id']}", headers=user["header"],
                        json={"target_value": 3500}).status_code == 404
    assert client.post(f"{API}/goals/{theirs['id']}/pause",
                       headers=user["header"]).status_code == 404
    assert client.delete(f"{API}/goals/{theirs['id']}",
                         headers=user["header"]).status_code == 404

    # 双方数据均未被越权修改
    mine_items = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    peer_items = client.get(f"{API}/goals", headers=peer["header"]).get_json()["data"]["items"]
    assert [i["id"] for i in mine_items] == [mine["id"]]
    assert [i["target_value"] for i in peer_items] == [3000]
    # 各自可正常删除自己的目标
    assert client.delete(f"{API}/goals/{mine['id']}",
                         headers=user["header"]).get_json()["data"] == {"deleted_count": 1}


# ════════════════════════════════════════════════════════════════════
# DB residual
# ════════════════════════════════════════════════════════════════════
def test_db_residual_no_non_test_data(client):
    """S：清理生效 —— 非 ``tst`` 前缀的**任何**业务行都不存在。"""
    counts = non_test_row_counts()
    assert set(counts.keys()) == set(BUSINESS_TABLES)
    leftovers = {k: v for k, v in counts.items() if v}
    assert not leftovers, f"存在非测试数据残留：{leftovers}"


def test_db_residual_health_goal_empty(client):
    """S：本批表 ``health_goal`` 行数为 0（测试结束后无残留）。"""
    counts = business_row_counts()
    assert counts["health_goal"] == 0
    assert counts["health_record"] == 0
