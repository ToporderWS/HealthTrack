# -*- coding: utf-8 -*-
"""B3 · PR-04 发起邮箱绑定（``POST /api/v1/auth/email/bind-request``）。

覆盖需求方 B3 授权 §八 中与 **bind-request** 有关的用例：

| # | 用例 |
|---|---|
| 1 | 首次发起：签发 ``email_bind`` 验证码并投递，且**不提前写 email** |
| 2 | 当前密码错误 ⇒ ``422 PASSWORD_INVALID``，零副作用 |
| 3 | 未登录 / 无效 Token ⇒ ``401`` |
| 4 | body 传 ``user_id`` ⇒ ``400 INVALID_PARAM``（全局身份守卫） |
| 5 | 邮箱格式非法 ⇒ ``422``（``errors[].field="email"`` / ``INVALID_FORMAT``） |
| 6 | 目标邮箱已被他人占用 ⇒ 与可绑定**恒等响应**（防枚举） |
| 7 | 大小写 / 空白经规范化后落同一 ``to`` |
| 8 | 60 秒冷却内重发 ⇒ 不签发新码、不重复发信 |
| 9 | 冷通过后签发新码 ⇒ 旧码立即失效（``CODE_MAX_ACTIVE_PER_PURPOSE=1``） |
| 10 | 契约边界：非 JSON / 缺字段 ⇒ ``400``；未知字段被 ``EXCLUDE`` |
| 11 | 投递层故障**不改变**对外响应（恒等响应不变） |
"""
from __future__ import annotations

import re

from app.core.password_reset import CODE_TTL_MINUTES, RESEND_COOLDOWN_SECONDS
from app.services import mail_service
from app.services.email_bind_service import REQUEST_MESSAGE

from tests.b3.conftest import (
    API,
    DEFAULT_PASSWORD,
    bind_email_via_api,
    exec_sql,
    latest_bind_code_for,
    login,
    one,
    register_token,
    req_bind,
    unique_email,
    access_token_of,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _body(resp) -> dict:
    return resp.get_json()


def _core(body: dict) -> dict:
    """剔除 ``request_id`` 后的可比对响应（``request_id`` 每次必然不同）。"""
    return {k: v for k, v in body.items() if k != "request_id"}


# ══════════════════════════════════════════════════════════════════
# 1. 首次发起 ⇒ 生成 email_bind 码 ＋ 投递，且**不提前写 email**
# ══════════════════════════════════════════════════════════════════
def test_bind_request_creates_email_bind_code_and_delivers(client):
    username, uid, token = register_token(client)
    email = unique_email()

    resp = req_bind(client, token, email)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = _body(resp)
    assert body["code"] == "OK"
    assert body["data"] is None
    assert body["message"] == REQUEST_MESSAGE

    # DB：恰 1 行 email_bind 挑战；未消费；TTL 与冻结常量一致；无明文列
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND purpose='email_bind'",
        u=uid,
    ) == 1
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 1
    delta = one(
        "SELECT TIMESTAMPDIFF(MINUTE, created_at, expires_at) FROM verification_code "
        "WHERE user_id=:u ORDER BY id DESC LIMIT 1",
        u=uid,
    )
    assert int(delta) == CODE_TTL_MINUTES
    code_hash = one(
        "SELECT code_hash FROM verification_code WHERE user_id=:u", u=uid
    )
    assert HEX64.match(str(code_hash))

    # 投递载荷：恰 1 封，purpose=email_bind，收件人＝目标邮箱
    box = mail_service.memory_outbox()
    assert len(box) == 1
    assert box[0]["purpose"] == "email_bind"
    assert box[0]["to"] == email
    assert latest_bind_code_for(email) is not None

    # ★ §四.1 / §Q-B3-04：本阶段**绝不**写 user_account.email
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None
    assert one("SELECT email_verified_at FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 2. 当前密码错误 ⇒ 422 PASSWORD_INVALID（复用既有语义），零副作用
# ══════════════════════════════════════════════════════════════════
def test_bind_request_wrong_current_password_rejected(client):
    username, uid, token = register_token(client)

    resp = req_bind(client, token, unique_email(), password="wrongpass1")
    assert resp.status_code == 422
    assert _body(resp)["code"] == "PASSWORD_INVALID"

    # 不生成码、不发信、不写 email
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 0
    assert mail_service.memory_outbox() == []
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 3. 未登录 / 无效 Token ⇒ 401
# ══════════════════════════════════════════════════════════════════
def test_bind_request_requires_login(client):
    anon = client.post(
        f"{API}/auth/email/bind-request",
        json={"email": unique_email(), "current_password": DEFAULT_PASSWORD},
    )
    assert anon.status_code == 401
    assert anon.get_json()["code"] == "UNAUTHENTICATED"

    bad = client.post(
        f"{API}/auth/email/bind-request",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"email": unique_email(), "current_password": DEFAULT_PASSWORD},
    )
    assert bad.status_code == 401
    assert mail_service.memory_outbox() == []


# ══════════════════════════════════════════════════════════════════
# 4. body / query 传 user_id ⇒ 400（身份只能来自 Token）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_rejects_client_supplied_user_id(client):
    username, uid, token = register_token(client)

    in_body = client.post(
        f"{API}/auth/email/bind-request",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": unique_email(), "current_password": DEFAULT_PASSWORD, "user_id": uid + 999},
    )
    assert in_body.status_code == 400
    assert in_body.get_json()["code"] == "INVALID_PARAM"

    in_query = client.post(
        f"{API}/auth/email/bind-request?user_id={uid + 999}",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": unique_email(), "current_password": DEFAULT_PASSWORD},
    )
    assert in_query.status_code == 400
    assert in_query.get_json()["code"] == "INVALID_PARAM"
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 0


# ══════════════════════════════════════════════════════════════════
# 5. 邮箱格式非法 ⇒ 422（字段级 INVALID_FORMAT），零副作用
# ══════════════════════════════════════════════════════════════════
def test_bind_request_invalid_email_format(client):
    username, uid, token = register_token(client)

    for bad in ("not-an-email", "a@b", "@example.com", "a@", "a b@example.com", "a@@b.com"):
        resp = req_bind(client, token, bad)
        assert resp.status_code == 422, (bad, resp.get_data(as_text=True))
        payload = resp.get_json()
        assert payload["code"] == "VALIDATION_FAILED"
        assert payload["errors"][0]["field"] == "email"
        assert payload["errors"][0]["code"] == "INVALID_FORMAT"

    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 0
    assert mail_service.memory_outbox() == []


# ══════════════════════════════════════════════════════════════════
# 6. 目标邮箱已被他人占用 ⇒ 与「可绑定」**逐字同框**（防枚举）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_taken_email_is_indistinguishable(client):
    # A 通过**真实契约**绑定一个邮箱
    _, _, token_a = register_token(client)
    taken = unique_email("owner")
    bind_email_via_api(client, token_a, taken)

    # B 试图绑定同一邮箱（PR-04 阶段**不做唯一性判定** ⇒ 恒等响应）
    _, _, token_b = register_token(client)
    on_taken = req_bind(client, token_b, taken)

    # 对照：B 绑定一个全新邮箱
    on_fresh = req_bind(client, token_b, unique_email("fresh"))

    assert on_taken.status_code == on_fresh.status_code == 200
    assert _core(_body(on_taken)) == _core(_body(on_fresh))
    # 响应中**绝不**回显邮箱（即便掩码）
    assert taken not in on_taken.get_data(as_text=True)


# ══════════════════════════════════════════════════════════════════
# 7. 大小写 / 空白 ⇒ 规范化后落同一 ``to``（canonical storage）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_normalizes_case_and_whitespace(client):
    username, uid, token = register_token(client)

    resp = req_bind(client, token, "  Foo.Bar@Example.COM  ")
    assert resp.status_code == 200
    box = mail_service.memory_outbox()
    assert len(box) == 1
    assert box[0]["to"] == "foo.bar@example.com"  # strip + lower，其余不动
    # 码只能对「规范化后的邮箱」有效（与 PR-05 同源）
    assert latest_bind_code_for("FOO.BAR@example.com") is not None


# ══════════════════════════════════════════════════════════════════
# 8. 60 秒冷却内重发 ⇒ 恒等 200，但**不签发新码 / 不重复发信**
# ══════════════════════════════════════════════════════════════════
def test_bind_request_resend_within_cooldown_issues_no_new_code(client):
    username, uid, token = register_token(client)
    email = unique_email()
    req_bind(client, token, email)
    first_hash = one(
        "SELECT code_hash FROM verification_code WHERE user_id=:u ORDER BY id DESC LIMIT 1", u=uid
    )

    again = req_bind(client, token, email)
    assert again.status_code == 200
    assert _core(_body(again)) == {"code": "OK", "message": REQUEST_MESSAGE, "data": None}
    # 码未增、哈希未变、邮件未多
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 1
    assert one("SELECT code_hash FROM verification_code WHERE user_id=:u", u=uid) == first_hash
    assert len(mail_service.memory_outbox()) == 1
    assert RESEND_COOLDOWN_SECONDS == 60  # 冷却来自冻结常量


# ══════════════════════════════════════════════════════════════════
# 9. 冷通过后签发新码 ⇒ 旧码立即失效（CODE_MAX_ACTIVE_PER_PURPOSE=1）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_new_code_invalidates_previous_code(client):
    username, uid, token = register_token(client)
    email = unique_email()
    req_bind(client, token, email)
    old_hash = one(
        "SELECT code_hash FROM verification_code WHERE user_id=:u ORDER BY id DESC LIMIT 1", u=uid
    )

    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u",
        u=uid,
    )
    assert req_bind(client, token, email).status_code == 200

    # 共 2 行：旧的已 consumed，新的未 consumed
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 2
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 1
    assert one(
        "SELECT consumed_at IS NOT NULL FROM verification_code WHERE code_hash=:h", h=old_hash
    ) == 1
    assert len(mail_service.memory_outbox()) == 2


# ══════════════════════════════════════════════════════════════════
# 10. 契约边界：非 JSON / 缺字段 ⇒ 400；未知字段 EXCLUDE（不改变行为）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_contract_boundaries(client):
    _, _, token = register_token(client)
    hdr = {"Authorization": f"Bearer {token}"}

    no_json = client.post(f"{API}/auth/email/bind-request", headers=hdr, data="x")
    assert no_json.status_code == 400
    assert no_json.get_json()["code"] == "INVALID_PARAM"

    empty = client.post(f"{API}/auth/email/bind-request", headers=hdr, json={})
    assert empty.status_code == 400
    fields = {e["field"] for e in empty.get_json()["errors"]}
    assert {"email", "current_password"} <= fields

    only_email = client.post(
        f"{API}/auth/email/bind-request", headers=hdr, json={"email": unique_email()}
    )
    assert only_email.status_code == 400
    assert only_email.get_json()["errors"][0]["field"] == "current_password"

    # 未知字段（purpose / code_hash）被 EXCLUDE ⇒ 不进任何逻辑
    sneaky = client.post(
        f"{API}/auth/email/bind-request",
        headers=hdr,
        json={
            "email": unique_email(),
            "current_password": DEFAULT_PASSWORD,
            "purpose": "password_reset",
            "code_hash": "deadbeef",
        },
    )
    assert sneaky.status_code == 200
    assert mail_service.memory_outbox()[0]["purpose"] == "email_bind"


# ══════════════════════════════════════════════════════════════════
# 11. 投递层故障**不改变**对外响应（恒等响应不变）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_delivery_failure_does_not_change_response(client, monkeypatch):
    _, _, token = register_token(client)
    email = unique_email()

    def _boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise RuntimeError("投递后端爆炸")

    monkeypatch.setattr(mail_service, "send_email_bind_code", _boom)
    resp = req_bind(client, token, email)
    assert resp.status_code == 200
    assert _core(_body(resp)) == {"code": "OK", "message": REQUEST_MESSAGE, "data": None}


# ══════════════════════════════════════════════════════════════════
# 12. 令牌在绑定链路中保持有效（为 PR-05 的会话保留判据打底）
# ══════════════════════════════════════════════════════════════════
def test_bind_request_does_not_touch_sessions(client):
    username, uid, token = register_token(client)
    assert login(client, username).status_code == 200  # 造第 2 条有效会话
    before = one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    )

    assert req_bind(client, token, unique_email()).status_code == 200
    assert access_token_of(client, username)  # 令牌仍可用
    after = one("SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid)
    assert after == before + 1  # 只有 access_token_of 新建的那条
