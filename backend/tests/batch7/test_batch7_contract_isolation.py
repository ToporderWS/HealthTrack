# -*- coding: utf-8 -*-
"""S2 第七批 —— 统一响应 envelope / 错误码契约 / 跨接口隔离。

本文件**不重复** D-01 / D-02 的业务用例，只验证：
统一 envelope、``X-Request-Id`` 一致性、错误响应结构、错误码契约、
``user_id`` 越权（query / body）、敏感字段不外泄、跨接口一致性。
"""
from __future__ import annotations

from tests.batch7.conftest import (
    add_goal,
    add_record,
    clear,
    confirm_payload,
    summary,
    ts_before,
)

ENVELOPE_KEYS = {"code", "message", "data", "request_id"}
FORBIDDEN_KEYS = ("file_path", "user_id", "password_hash", "refresh_token",
                  "access_token", "jwt", "secret", "session_id", "token")


def _blob(resp) -> str:
    return resp.get_data(as_text=True)


# ════════════════════════════════════════════════════════════════════
# envelope
# ════════════════════════════════════════════════════════════════════
def test_d01_envelope_exactly_four_keys(client, user):
    resp = summary(client, user["header"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == ENVELOPE_KEYS, sorted(body.keys())
    assert body["code"] == "OK"
    assert resp.headers.get("X-Request-Id") == body["request_id"]
    assert body["request_id"]


def test_d02_envelope_exactly_four_keys(client, rich_user):
    resp = clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == ENVELOPE_KEYS, sorted(body.keys())
    assert body["code"] == "OK"
    assert resp.headers.get("X-Request-Id") == body["request_id"]


def test_request_id_unique_per_request(client, user):
    """每个请求的 ``request_id`` **互不相同**。"""
    ids = [
        summary(client, user["header"]).get_json()["request_id"]
        for _ in range(3)
    ]
    assert len(set(ids)) == 3, ids


def test_error_envelopes_are_consistent(client, rich_user):
    """错误响应同样为统一 envelope，且 ``data`` 为 ``null``。"""
    cases = [
        # (响应, 期望 HTTP, 期望 code)
        (client.get("/api/v1/me/data/summary"), 401, "UNAUTHENTICATED"),
        (summary(client, {"Authorization": "Bearer bad"}), 401, "UNAUTHENTICATED"),
        (clear(client, rich_user["header"], confirm_text="错", password="x",
               acknowledge_irreversible=True), 422, "VALIDATION_FAILED"),
        (clear(client, rich_user["header"], **confirm_payload("wrong-password")),
         422, "PASSWORD_INVALID"),
    ]
    for resp, status, code in cases:
        assert resp.status_code == status, (resp.status_code, resp.get_json())
        body = resp.get_json()
        assert set(body.keys()) <= {"code", "message", "data", "request_id", "errors"}, body.keys()
        assert body["code"] == code, body
        assert body["data"] is None, body
        assert body["request_id"]
        assert resp.headers.get("X-Request-Id") == body["request_id"]


def test_internal_error_envelope(client, rich_user, monkeypatch):
    """``500`` 同样是统一 envelope，且**不返回任何内部细节**。"""
    from app.services import data_service

    def _boom(*_args, **_kwargs):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(data_service, "_soft_delete_records", _boom)
    resp = clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))

    assert resp.status_code == 500
    body = resp.get_json()
    assert set(body.keys()) == ENVELOPE_KEYS
    assert body["code"] == "INTERNAL_ERROR"
    assert body["data"] is None
    assert "secret-internal-detail" not in _blob(resp)
    assert "Traceback" not in _blob(resp)


# ════════════════════════════════════════════════════════════════════
# user_id 越权
# ════════════════════════════════════════════════════════════════════
def test_d01_query_user_id_rejected(client, user, peer):
    """D-01：query 携带 ``user_id`` → ``400 INVALID_PARAM``。"""
    resp = client.get(f"/api/v1/me/data/summary?user_id={peer['user_id']}",
                      headers=user["header"])
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"


def test_d02_body_user_id_rejected(client, user, peer):
    """D-02：请求体携带 ``user_id`` → ``400 INVALID_PARAM``（全局守卫）。"""
    payload = confirm_payload(user["password"])
    payload["user_id"] = peer["user_id"]
    resp = clear(client, user["header"], **payload)
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"


def test_d01_ignores_other_users_data(client, rich_user, peer):
    """D-01 只统计本人（对端造数后本端计数不变）。"""
    before = summary(client, rich_user["header"]).get_json()["data"]
    add_record(client, peer["header"], metric_type="weight", value_1="55.00",
               recorded_at=ts_before(days=1))
    add_goal(peer["user_id"], goal_type="water", status=1)
    after = summary(client, rich_user["header"]).get_json()["data"]
    assert before == after


def test_d02_does_not_leak_peer_data(client, rich_user, peer):
    """D-02 清空本端后，对端 D-01 计数不变（不得跨用户）。"""
    add_record(client, peer["header"], metric_type="water", value_1=300,
               recorded_at=ts_before(days=1))
    before = summary(client, peer["header"]).get_json()["data"]

    clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))

    assert summary(client, peer["header"]).get_json()["data"] == before


# ════════════════════════════════════════════════════════════════════
# 敏感字段不外泄
# ════════════════════════════════════════════════════════════════════
def test_d01_no_sensitive_keys(client, rich_user):
    """D-01 响应不含 ``user_id`` / Token / 密钥等内部字段。"""
    text = _blob(summary(client, rich_user["header"]))
    for key in FORBIDDEN_KEYS:
        assert key not in text, key


def test_d02_no_sensitive_keys(client, rich_user):
    """D-02 响应不含 ``user_id`` / Token / 密钥 / 内部主键。"""
    text = _blob(clear(client, rich_user["header"],
                       **confirm_payload(rich_user["password"])))
    for key in FORBIDDEN_KEYS:
        assert key not in text, key
    assert rich_user["username"] not in text


def test_error_responses_do_not_leak(client, rich_user):
    """错误响应不泄漏账号 / 密码 / 内部标识。"""
    resp = clear(client, rich_user["header"], **confirm_payload("wrong-password"))
    text = _blob(resp)
    assert rich_user["username"] not in text
    assert "password_hash" not in text
    assert "wrong-password" not in text


# ════════════════════════════════════════════════════════════════════
# 跨接口一致性
# ════════════════════════════════════════════════════════════════════
def test_clear_then_summary_is_consistent(client, rich_user):
    """D-02 → D-01 一致：清空后总览归零（含 goals / profile）。"""
    assert summary(client, rich_user["header"]).get_json()["data"]["total_records"] == 3
    clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))
    data = summary(client, rich_user["header"]).get_json()["data"]
    assert data["total_records"] == 0
    assert data["by_metric"] == []
    assert data["goals"] == {"active_count": 0, "paused_count": 0}
    assert data["profile"] == {"health_fields_filled": 0, "health_fields_total": 6}


def test_summary_then_clear_counts_match(client, rich_user):
    """D-01 的 ``total_records`` 与 D-02 的 ``deleted_records`` 一致。"""
    total = summary(client, rich_user["header"]).get_json()["data"]["total_records"]
    body = clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))
    assert body.get_json()["data"]["deleted_records"] == total
