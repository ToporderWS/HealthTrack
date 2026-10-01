# -*- coding: utf-8 -*-
"""S2 第三批 L/P/Q/R/S（认证守卫 / 响应契约 / 隔离 / 残留检查）。

覆盖验收项：
- L：P / R 全部接口必须认证（免 Token → 401）
- P/Q：统一响应契约 ``{code,message,data,request_id}`` + 32 位 ``request_id``
  且与 ``X-Request-Id`` 一致
- R/S：客户端 ``user_id`` 一律 400；跨用户零泄露；软删不可见
- DB residual：测试结束后 8 张业务表**行数合计 0**
"""
from __future__ import annotations

import re

from tests.batch3.conftest import (
    API,
    BUSINESS_TABLES,
    business_row_counts,
    created_record,
    non_test_row_counts,
    post_record,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
WEIGHT = {"metric_type": "weight", "value_1": 72.5, "recorded_at": "2026-09-13 07:30:00"}

#: P / R 全部接口：(method, path_template)
ENDPOINTS = (
    ("GET", "/profile"),
    ("PUT", "/profile"),
    ("POST", "/records"),
    ("GET", "/records"),
    ("GET", "/records/count"),
    ("GET", "/records/options"),
    ("POST", "/records/batch-delete"),
    ("GET", "/records/{id}"),
    ("PATCH", "/records/{id}"),
    ("DELETE", "/records/{id}"),
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
    """L：P / R 全部接口免 Token → 401（不泄露任何业务信息）。"""
    for method, path in ENDPOINTS:
        url = f"{API}{path.replace('{id}', '1')}"
        kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        resp = getattr(client, method.lower())(url, **kwargs)
        assert resp.status_code == 401, (method, path, resp.status_code)
        body = resp.get_json()
        assert body["code"] == "UNAUTHENTICATED"
        assert body["data"] is None


def test_l_invalid_token_rejected(client):
    """L：伪造 / 畸形 Token → 401。"""
    for header in ({"Authorization": "Bearer not-a-jwt"},
                   {"Authorization": "Basic abc"},
                   {"Authorization": "Bearer "}):
        assert client.get(f"{API}/profile", headers=header).status_code == 401


# ════════════════════════════════════════════════════════════════════
# P / Q —— 响应契约
# ════════════════════════════════════════════════════════════════════
def test_pq_success_contract_on_every_endpoint(client, user):
    """P/Q：全部 P / R 接口的成功响应均满足四键 + request_id 契约。"""
    record = created_record(post_record(client, user["header"], WEIGHT))
    rid = record["id"]

    calls = {
        ("GET", "/profile"): client.get(f"{API}/profile", headers=user["header"]),
        ("PUT", "/profile"): client.put(f"{API}/profile", headers=user["header"],
                                        json={"nickname": "小测"}),
        ("GET", "/records"): client.get(f"{API}/records", headers=user["header"]),
        ("GET", "/records/count"): client.get(f"{API}/records/count", headers=user["header"]),
        ("GET", "/records/options"): client.get(f"{API}/records/options", headers=user["header"]),
        ("GET", "/records/{id}"): client.get(f"{API}/records/{rid}", headers=user["header"]),
        ("PATCH", "/records/{id}"): client.patch(f"{API}/records/{rid}", headers=user["header"],
                                                 json={"note": "备注"}),
        ("POST", "/records/batch-delete"): client.post(
            f"{API}/records/batch-delete", headers=user["header"],
            json={"metric_type": "weight", "password": user["password"]}),
    }
    for (method, path), resp in calls.items():
        assert resp.status_code in (200, 201), (method, path, resp.get_json())
        body = _assert_contract(resp)
        assert body["code"] == "OK", (method, path, body)

    # 写类接口单独校验（避免相互影响）
    created = post_record(client, user["header"],
                          {**WEIGHT, "recorded_at": "2026-09-13 09:00:00"})
    assert created.status_code == 201
    _assert_contract(created)

    new_record = created_record(post_record(client, user["header"],
                                            {**WEIGHT, "recorded_at": "2026-09-13 10:00:00"}))
    deleted = client.delete(f"{API}/records/{new_record['id']}", headers=user["header"])
    assert deleted.status_code == 200
    _assert_contract(deleted)


def test_pq_failure_contract_carries_errors_only_when_field_level(client, user):
    """P/Q：失败响应四键齐全；``errors[]`` 仅在字段级明细存在时出现。"""
    missing = post_record(client, user["header"], {"value_1": 1})          # 缺 metric_type → 400
    assert missing.status_code == 400
    body = _assert_contract(missing, allow_errors=True)
    assert body["code"] == "INVALID_PARAM"
    assert body["errors"] and body["errors"][0]["code"] == "REQUIRED"

    not_found = client.get(f"{API}/records/99999999", headers=user["header"])
    assert not_found.status_code == 404
    body = _assert_contract(not_found)
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert body["data"] is None

    hard = post_record(client, user["header"],
                       {"metric_type": "weight", "value_1": 5000,
                        "recorded_at": "2026-09-13 07:30:00"})
    assert hard.status_code == 422
    body = _assert_contract(hard, allow_errors=True)
    assert body["code"] == "VALIDATION_FAILED"

    soft = post_record(client, user["header"],
                       {"metric_type": "weight", "value_1": 320,
                        "recorded_at": "2026-09-13 07:30:00"})
    assert soft.status_code == 200
    body = _assert_contract(soft)                       # 软提示**不带** errors[]
    assert body["code"] == "SOFT_WARNING"
    assert body["data"]["requires_confirm"] is True


def test_pq_request_id_unique_per_request(client, user):
    """Q：``request_id`` 每请求唯一。"""
    ids = set()
    for _ in range(6):
        body = client.get(f"{API}/records/options", headers=user["header"]).get_json()
        ids.add(body["request_id"])
    assert len(ids) == 6


# ════════════════════════════════════════════════════════════════════
# R / S —— 客户端 user_id 与隔离
# ════════════════════════════════════════════════════════════════════
def test_r_client_user_id_in_query_rejected(client, user):
    """R：任何 P / R 接口带 query ``user_id`` → 400。"""
    for method, path in ENDPOINTS:
        url = f"{API}{path.replace('{id}', '1')}?user_id=1"
        kwargs = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        resp = getattr(client, method.lower())(url, headers=user["header"], **kwargs)
        assert resp.status_code == 400, (method, path, resp.status_code)
        assert resp.get_json()["code"] == "INVALID_PARAM"


def test_r_client_user_id_in_body_rejected(client, user):
    """R：任何 P / R 接口带请求体 ``user_id`` → 400。"""
    record = created_record(post_record(client, user["header"], WEIGHT))
    targets = (
        ("PUT", "/profile"),
        ("POST", "/records"),
        ("POST", "/records/batch-delete"),
        ("PATCH", f"/records/{record['id']}"),
    )
    for method, path in targets:
        resp = getattr(client, method.lower())(f"{API}{path}", headers=user["header"],
                                               json={"user_id": 1})
        assert resp.status_code == 400, (method, path, resp.status_code)
        assert resp.get_json()["code"] == "INVALID_PARAM"
    # 记录数未变化
    assert client.get(f"{API}/records/count",
                      headers=user["header"]).get_json()["data"]["count"] == 1


def test_s_cross_user_isolation_summary(client, user, peer):
    """S：跨用户全链路隔离（P-01 / P-02 / R-01~R-08）。"""
    # 各自写档案
    client.put(f"{API}/profile", headers=user["header"], json={"nickname": "甲", "height_cm": 170.0})
    client.put(f"{API}/profile", headers=peer["header"], json={"nickname": "乙", "height_cm": 180.0})
    assert client.get(f"{API}/profile",
                      headers=user["header"]).get_json()["data"]["profile"]["nickname"] == "甲"
    assert client.get(f"{API}/profile",
                      headers=peer["header"]).get_json()["data"]["profile"]["nickname"] == "乙"

    # 各自写记录
    mine = created_record(post_record(client, user["header"], WEIGHT))
    theirs = created_record(post_record(client, peer["header"], WEIGHT))

    assert client.get(f"{API}/records/count",
                      headers=user["header"]).get_json()["data"]["count"] == 1
    # 跨用户：详情 / 编辑 / 删除 / 批量 全 404 或零影响
    assert client.get(f"{API}/records/{theirs['id']}", headers=user["header"]).status_code == 404
    assert client.patch(f"{API}/records/{theirs['id']}", headers=user["header"],
                        json={"note": "x"}).status_code == 404
    assert client.delete(f"{API}/records/{theirs['id']}", headers=user["header"]).status_code == 404
    assert client.post(f"{API}/records/batch-delete", headers=user["header"],
                       json={"metric_type": "weight", "password": user["password"]}
                       ).get_json()["data"] == {"deleted_count": 1}
    assert client.get(f"{API}/records/count",
                      headers=peer["header"]).get_json()["data"]["count"] == 1
    assert client.get(f"{API}/records/{mine['id']}",
                      headers=user["header"]).status_code == 404      # 自己那条已被批量删除


# ════════════════════════════════════════════════════════════════════
# DB residual
# ════════════════════════════════════════════════════════════════════
def test_db_residual_check_no_non_test_data(client):
    """S：清理生效 —— 非 ``tst`` 前缀的**任何**业务行都不存在。

    - ``health_record`` / ``record_tag`` / ``health_goal`` / ``export_job``：**总量为 0**
      （本批只写前两张，且每个测试前后均被清理）；
    - 账号 / 档案 / 会话 / 登录失败状态：仅允许存在 ``tst`` 前缀行
      （会话级装置在整体结束时统一清除）。
    """
    counts = non_test_row_counts()
    assert set(counts.keys()) == set(BUSINESS_TABLES)
    leftovers = {k: v for k, v in counts.items() if v}
    assert not leftovers, f"存在非测试数据残留：{leftovers}"


def test_db_residual_check_b3_tables_empty(client):
    """S：本批两张表（``health_record`` / ``record_tag``）行数为 0。"""
    counts = business_row_counts()
    assert counts["health_record"] == 0
    assert counts["record_tag"] == 0
