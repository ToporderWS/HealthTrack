# -*- coding: utf-8 -*-
"""S2 第六批 —— 统一响应契约 + 身份隔离 + 防注入。

覆盖：四字段 envelope（含 ``X-Request-Id`` 一致性）/ 401 / 身份守卫
（``user_id`` 注入 → ``400``）/ 跨用户零泄漏 / 导出内容与任务列表的严格归属。
"""
from __future__ import annotations

import json
import re

from tests.batch6.conftest import (
    API,
    download,
    export_detail,
    export_file_bytes,
    job_row,
    list_exports,
    new_export,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")


# ════════════════════════════════════════════════════════════════════
# 统一响应契约
# ════════════════════════════════════════════════════════════════════
def test_envelope_four_fields_and_request_id(client, exporter):
    """契约：JSON 响应恒为 ``{code,message,data,request_id}``；``X-Request-Id`` 与 body 一致。"""
    resp = client.post(f"{API}/exports", headers=exporter["header"],
                       json={"format": "csv", "password": exporter["password"]})
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "request_id"}
    assert body["code"] == "OK"
    assert HEX32.match(body["request_id"])
    assert resp.headers["X-Request-Id"] == body["request_id"]


def test_envelope_on_detail_and_list(client, exporter):
    """契约：E-02 / E-04 同样满足四字段与 ``X-Request-Id`` 一致。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    for resp in (export_detail(client, exporter["header"], int(created["export_id"])),
                 list_exports(client, exporter["header"])):
        body = resp.get_json()
        assert set(body.keys()) == {"code", "message", "data", "request_id"}
        assert HEX32.match(body["request_id"])
        assert resp.headers["X-Request-Id"] == body["request_id"]
        assert body["request_id"] != created["export_id"]


def test_error_envelope(client, exporter):
    """契约：错误响应同为四字段，``data = null``，``code`` 为冻结错误码。"""
    resp = export_detail(client, exporter["header"], 987654321)
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "request_id"}
    assert body["data"] is None
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert resp.headers["X-Request-Id"] == body["request_id"]

    expired = client.post(f"{API}/exports", headers=exporter["header"],
                          json={"format": "xml", "password": exporter["password"]})
    bad = expired.get_json()
    assert bad["code"] == "INVALID_PARAM" and bad["data"] is None


def test_request_id_unique_per_request(client, exporter):
    """契约：``request_id`` 每次请求唯一。"""
    ids = set()
    for _ in range(3):
        resp = list_exports(client, exporter["header"])
        ids.add(resp.get_json()["request_id"])
    assert len(ids) == 3


# ════════════════════════════════════════════════════════════════════
# 鉴权
# ════════════════════════════════════════════════════════════════════
def test_all_four_require_auth(client):
    """鉴权：E-01 ~ E-04 未登录一律 ``401 UNAUTHENTICATED``。"""
    responses = [
        client.post(f"{API}/exports", json={"format": "csv", "password": "abc12345"}),
        client.get(f"{API}/exports"),
        client.get(f"{API}/exports/1"),
        client.get(f"{API}/exports/1/download?file_token={'0' * 32}"),
    ]
    for resp in responses:
        assert resp.status_code == 401, resp.get_json()
        assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_bad_token_is_401(client, user):
    """鉴权：伪造 / 失效 Token → ``401``。"""
    headers = {"Authorization": "Bearer not-a-real-token"}
    assert client.get(f"{API}/exports", headers=headers).status_code == 401
    assert client.post(f"{API}/exports", headers=headers,
                       json={"format": "csv", "password": user["password"]}).status_code == 401


# ════════════════════════════════════════════════════════════════════
# 身份守卫 —— user_id 注入
# ════════════════════════════════════════════════════════════════════
def test_query_user_id_rejected(client, user):
    """守卫：query 携带 ``user_id`` → ``400 INVALID_PARAM``。"""
    for path in ("/api/v1/exports", "/api/v1/exports?user_id=1",
                 "/api/v1/exports/1?user_id=1",
                 "/api/v1/exports/1/download?file_token=x&user_id=1"):
        resp = client.get(path, headers=user["header"])
        if "user_id" in path:
            assert resp.status_code == 400, path
            assert resp.get_json()["code"] == "INVALID_PARAM"


def test_body_user_id_rejected(client, user):
    """守卫：请求体携带 ``user_id`` → ``400 INVALID_PARAM``。"""
    resp = client.post(f"{API}/exports", headers=user["header"],
                       json={"format": "csv", "password": user["password"], "user_id": 999})
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"


def test_forged_peer_user_id_cannot_access(client, exporter, peer):
    """隔离：伪造对端 ``user_id`` 一律被守卫拦下，且正常调用**零泄漏**。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    export_id = int(created["export_id"])
    token = job_row(export_id)["file_token"]

    forged = client.post(f"{API}/exports", headers=exporter["header"],
                         json={"format": "csv", "password": exporter["password"],
                               "user_id": peer["user_id"]})
    assert forged.status_code == 400

    assert export_detail(client, peer["header"], export_id).status_code == 404
    assert download(client, peer["header"], export_id, token).status_code == 404
    assert list_exports(client, peer["header"]).get_json()["data"]["items"] == []


# ════════════════════════════════════════════════════════════════════
# 数据归属 —— 导出内容严格本人
# ════════════════════════════════════════════════════════════════════
def test_export_content_contains_only_own_data(client, exporter, peer):
    """隔离：导出文件**只含本人**数据，对端记录与其标签均不出现。"""
    from tests.batch6.conftest import add_record, ts_before

    add_record(client, peer["header"], metric_type="water", value_1=1234,
               recorded_at=ts_before(days=1), note="PEER-ONLY-NOTE")

    created = new_export(client, exporter["header"], format="json",
                         password=exporter["password"])
    content = export_file_bytes(int(created["export_id"])).decode("utf-8")
    records = json.loads(content)["records"]

    assert created["record_count"] == 3
    assert len(records) == 3
    assert "PEER-ONLY-NOTE" not in content
    assert all(r["metric_type"] != "water" or r["value_1"] != 1234 for r in records)


def test_job_row_bound_to_caller_only(client, exporter, peer):
    """隔离：任务行的 ``user_id`` 恒为调用者（Token 解析结果）。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    row = job_row(int(created["export_id"]))
    assert row["user_id"] == exporter["user_id"] != peer["user_id"]


def test_no_sensitive_internal_fields_in_payloads(client, exporter):
    """隔离：所有 JSON 载荷**不含** ``file_path`` / ``user_id`` / 会话或密钥字段。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    texts = [
        json.dumps(created, ensure_ascii=False),
        export_detail(client, exporter["header"], int(created["export_id"])).get_data(as_text=True),
        list_exports(client, exporter["header"]).get_data(as_text=True),
    ]
    for text in texts:
        for forbidden in ("file_path", "user_id", "password_hash", "refresh_token",
                          "access_token", "secret", "session"):
            assert forbidden not in text, forbidden
