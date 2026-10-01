# -*- coding: utf-8 -*-
"""S2 第八批 A-07 —— 统一 envelope / 隔离 / 不泄漏 验收用例。

覆盖：成功与失败响应**统一 envelope**（4 键 + 可选 ``errors``）· ``X-Request-Id`` 与 body
``request_id`` 一致 · ``request_id`` 每请求唯一 · 401/422/500 错误响应一致且 ``data is None`` ·
请求体 ``user_id`` 被全局守卫拦截 · 注销**不泄漏**对端数据 · 响应无敏感键 ·
注销后 8 张表归零的一致性。

★ 全部用例**只**操作 ``tst`` 独立测试账号。
"""
from __future__ import annotations

from tests.batch8.conftest import (
    API,
    account_row,
    close_account,
    close_payload,
    goal_rows,
    job_rows,
    login_failure_rows,
    make_user,
    profile_row,
    record_rows,
    session_rows,
    tag_rows,
)

#: 绝不允许出现在响应中的键（内部 / 敏感）
FORBIDDEN_KEYS = {
    "password_hash", "password_algo", "role", "refresh_token_hash",
    "access_token_id", "file_path", "file_token", "user_id",
    "deleted_marker", "is_deleted", "deleted_at", "export_pwd_fail_count",
    "change_pwd_fail_count", "traceback", "sql", "stack",
}


def _walk_keys(node, found):
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(str(key))
            _walk_keys(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_keys(item, found)


def _keys_of(body) -> set:
    found: set = set()
    _walk_keys(body, found)
    return found


# ════════════════════════════════════════════════════════════════════
# envelope
# ════════════════════════════════════════════════════════════════════
def test_a07_success_envelope_exactly_four_keys(client, user):
    resp = close_account(client, user["header"], **close_payload(user["password"]))
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "request_id"}
    assert body["request_id"], body
    assert resp.headers.get("X-Request-Id") == body["request_id"]


def test_a07_error_envelope_shape(client, user):
    """422 错误 envelope：4 键 + 可选 ``errors``；``data is None``。"""
    resp = close_account(client, user["header"], **close_payload("wrong-pass-1"))
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert {"code", "message", "data", "request_id"}.issubset(set(body.keys()))
    assert set(body.keys()) - {"errors"} == {"code", "message", "data", "request_id"}
    assert body["code"] == "PASSWORD_INVALID"
    assert body["data"] is None
    assert resp.headers.get("X-Request-Id") == body["request_id"]


def test_a07_unauthorized_envelope(client, user):
    """401：``data is None`` + 统一错误码。"""
    _close_ok(client, user)
    resp = client.get(f"{API}/users/me", headers=user["header"])
    assert resp.status_code == 401, resp.get_json()
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "request_id"}
    assert body["code"] == "UNAUTHENTICATED"
    assert body["data"] is None


def test_a07_validation_error_carries_field_detail(client, user):
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], confirm_text="不对"))
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert isinstance(body.get("errors"), list) and body["errors"]
    assert set(body["errors"][0].keys()) == {"field", "code", "message"}


def test_a07_request_id_is_unique_per_request(client, user):
    first = close_account(client, user["header"], **close_payload("wrong-pass-1"))
    second = close_account(client, user["header"], **close_payload("wrong-pass-2"))
    assert first.get_json()["request_id"] != second.get_json()["request_id"]


def test_a07_500_envelope_has_no_internal_details(client, rich_user, monkeypatch):
    from app.services import account_service as svc

    def _boom(db, model, *criteria, **kwargs):  # noqa: ANN001, ANN202
        raise RuntimeError("internal-should-not-leak")

    monkeypatch.setattr(svc, "_purge", _boom)
    resp = close_account(client, rich_user["header"],
                         **close_payload(rich_user["password"]))
    assert resp.status_code == 500, resp.get_json()
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "request_id"}
    assert body["code"] == "INTERNAL_ERROR"
    assert body["data"] is None
    assert "internal-should-not-leak" not in resp.get_data(as_text=True)


# ════════════════════════════════════════════════════════════════════
# 越权 / 隔离
# ════════════════════════════════════════════════════════════════════
def test_a07_query_user_id_rejected(client, user):
    resp = client.delete(f"{API}/users/me?user_id=1", headers=user["header"],
                         json=close_payload(user["password"]))
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"
    assert account_row(user["user_id"]) is not None


def test_a07_body_user_id_rejected(client, user):
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], user_id=user["user_id"]))
    assert resp.status_code == 400, resp.get_json()
    assert account_row(user["user_id"]) is not None


def test_a07_cannot_close_other_account(client, user, peer):
    """★ E：A 的 Token + 指向 B 的参数 → 只注销 A，B 完好。"""
    peer_uid = peer["user_id"]
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], target_user_id=peer_uid))
    assert resp.status_code == 200, resp.get_json()
    assert account_row(user["user_id"]) is None
    assert account_row(peer_uid) is not None
    assert session_rows(peer_uid), "B 的会话必须保持"


def test_a07_does_not_leak_peer_data(client, user, peer):
    """注销 A 的响应中不得出现 B 的任何标识 / 数据键。"""
    resp = close_account(client, user["header"], **close_payload(user["password"]))
    body = resp.get_json()
    keys = _keys_of(body)
    assert not (keys & FORBIDDEN_KEYS), keys & FORBIDDEN_KEYS
    assert peer["username"] not in resp.get_data(as_text=True)


def test_a07_response_has_no_sensitive_keys(client, rich_user):
    resp = close_account(client, rich_user["header"],
                         **close_payload(rich_user["password"]))
    keys = _keys_of(resp.get_json())
    assert not (keys & FORBIDDEN_KEYS), keys & FORBIDDEN_KEYS


def test_a07_error_response_has_no_sensitive_keys(client, user):
    resp = close_account(client, user["header"], **close_payload("wrong-pass-1"))
    keys = _keys_of(resp.get_json())
    assert not (keys & FORBIDDEN_KEYS), keys & FORBIDDEN_KEYS


# ════════════════════════════════════════════════════════════════════
# 归零一致性
# ════════════════════════════════════════════════════════════════════
def test_a07_all_tables_zero_after_close(client, rich_user):
    uid = rich_user["user_id"]
    _close_ok(client, rich_user)
    assert account_row(uid) is None
    assert profile_row(uid) is None
    assert record_rows(uid) == []
    assert tag_rows(uid) == []
    assert goal_rows(uid) == []
    assert session_rows(uid) == []
    assert job_rows(uid) == []
    assert login_failure_rows(rich_user["username"]) == []


def test_a07_peer_fully_intact_after_close(client, rich_user, peer):
    """对端账号 8 张表数据（有数据的那些）在注销后完全不变。"""
    peer_uid = peer["user_id"]
    before = (account_row(peer_uid), len(session_rows(peer_uid)),
              len(login_failure_rows(peer["username"])))
    _close_ok(client, rich_user)
    after = (account_row(peer_uid), len(session_rows(peer_uid)),
             len(login_failure_rows(peer["username"])))
    assert after == before


def _close_ok(client, account):
    resp = close_account(client, account["header"], **close_payload(account["password"]))
    assert resp.status_code == 200, (resp.status_code, resp.get_json())
    return resp.get_json()
