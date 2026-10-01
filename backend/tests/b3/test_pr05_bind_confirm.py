# -*- coding: utf-8 -*-
"""B3 · PR-05 校验绑定验证码（``POST /api/v1/auth/email/bind-confirm``）。

覆盖需求方 B3 授权 §八 中与 **bind-confirm** 有关的用例：

| # | 用例 |
|---|---|
| 1 | 首次绑定成功：同事务写 ``email`` ＋ ``email_verified_at`` ＋ 消费该码 |
| 2 | 改绑成功：覆盖旧邮箱 ＋ 旧邮箱立即释放 |
| 3 | 当前密码错误 ⇒ ``422 PASSWORD_INVALID``，零副作用 |
| 4 | 未登录 / 无效 Token ⇒ ``401`` |
| 5 | body 传 ``user_id`` ⇒ ``400``（全局身份守卫） |
| 6 | 邮箱格式非法 ⇒ ``422``（字段级 ``INVALID_FORMAT``） |
| 7 | 错误验证码 ⇒ 中性 ``422``，``attempt_count`` ＋1 |
| 8 | 过期验证码 ⇒ 中性 ``422``（且不消耗尝试次数） |
| 9 | 尝试次数达上限 ⇒ ``429 SESSION_VERIFY_ABORTED`` ⇒ 码作废 ⇒ 再试中性 ``422`` |
| 10 | 同一码重放（第二次 confirm）⇒ 中性 ``422``，**不产生第二次绑定** |
| 11 | 并发两次 confirm ⇒ **恰好 1 次成功**（行锁 ＋ 唯一索引） |
| 12 | 邮箱唯一冲突 ⇒ ``409 EMAIL_TAKEN`` ＋ **整事务回滚（无半写入）** |
| 13 | 大小写 / 空白归一后的唯一冲突 ⇒ ``409`` |
| 14 | **码与邮箱绑定**：为 A 邮箱申请的码不能用于绑定 B 邮箱 |
| 15 | 绑定成功后**会话保留**（§Q-B3-11：不撤销任何 Session） |
| 16 | 契约边界：非 JSON / 缺字段 ⇒ ``400``；未知字段 ``EXCLUDE`` |
"""
from __future__ import annotations

import threading

from app.core.password_reset import CODE_MAX_ATTEMPTS
from app.services import mail_service
from app.services.email_bind_service import CONFIRM_OK_MESSAGE, INVALID_CODE_MESSAGE

from tests.b3.conftest import (
    API,
    DEFAULT_PASSWORD,
    auth_header,
    bind_email_via_api,
    exec_sql,
    latest_bind_code_for,
    one,
    register_token,
    req_bind,
    req_confirm_bind,
    unique_email,
)


def _start_bind(client, token: str, email: str):
    """发起绑定并返回 ``(email, code)``（冷却不受影响 —— 每个账号只调用一次）。"""
    assert req_bind(client, token, email).status_code == 200
    code = latest_bind_code_for(email)
    assert code is not None, "PR-04 未投递 email_bind 验证码"
    return email, code


# ══════════════════════════════════════════════════════════════════
# 1. 首次绑定成功（核心闭环）
# ══════════════════════════════════════════════════════════════════
def test_first_bind_success_writes_email_and_verified_at(client):
    username, uid, token = register_token(client)
    email = unique_email()
    _, code = _start_bind(client, token, email)

    resp = req_confirm_bind(client, token, email, code)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["code"] == "OK"
    assert body["message"] == CONFIRM_OK_MESSAGE
    assert body["data"] == {"email_bound": True}

    # 落库：email 规范形 ＋ email_verified_at 非空（配对 CHECK 同时满足）
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == email
    assert one("SELECT email_verified_at IS NOT NULL FROM user_account WHERE id=:u", u=uid) == 1
    # 该码已消费
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 0
    # 响应**不回显**邮箱
    assert email not in resp.get_data(as_text=True)


# ══════════════════════════════════════════════════════════════════
# 2. 改绑成功：覆盖旧邮箱；旧邮箱立即释放（可被他人绑定）
# ══════════════════════════════════════════════════════════════════
def test_rebind_overwrites_old_email_and_releases_it(client):
    _, uid, token = register_token(client)
    first = unique_email("old")
    second = unique_email("new")
    bind_email_via_api(client, token, first)
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == first

    # 解除冷却后改绑
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u AND purpose='email_bind'",
        u=uid,
    )
    _, code = _start_bind(client, token, second)
    assert req_confirm_bind(client, token, second, code).status_code == 200

    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == second

    # 旧邮箱已被释放：另一个账号可以成功绑定它
    _, _, token2 = register_token(client)
    bind_email_via_api(client, token2, first)


# ══════════════════════════════════════════════════════════════════
# 3. 当前密码错误 ⇒ 422 PASSWORD_INVALID，零副作用
# ══════════════════════════════════════════════════════════════════
def test_confirm_wrong_current_password_rejected(client):
    _, uid, token = register_token(client)
    email, code = _start_bind(client, token, unique_email())

    resp = req_confirm_bind(client, token, email, code, password="wrongpass1")
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "PASSWORD_INVALID"
    # email 未写、码未消费
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 1


# ══════════════════════════════════════════════════════════════════
# 4. 未登录 ⇒ 401
# ══════════════════════════════════════════════════════════════════
def test_confirm_requires_login(client):
    anon = client.post(
        f"{API}/auth/email/bind-confirm",
        json={"email": unique_email(), "code": "123456", "current_password": DEFAULT_PASSWORD},
    )
    assert anon.status_code == 401
    assert anon.get_json()["code"] == "UNAUTHENTICATED"

    bad = client.post(
        f"{API}/auth/email/bind-confirm",
        headers={"Authorization": "Bearer nope"},
        json={"email": unique_email(), "code": "123456", "current_password": DEFAULT_PASSWORD},
    )
    assert bad.status_code == 401


# ══════════════════════════════════════════════════════════════════
# 5. body 传 user_id ⇒ 400
# ══════════════════════════════════════════════════════════════════
def test_confirm_rejects_client_supplied_user_id(client):
    _, uid, token = register_token(client)
    email, code = _start_bind(client, token, unique_email())

    resp = client.post(
        f"{API}/auth/email/bind-confirm",
        headers=auth_header(token),
        json={
            "email": email,
            "code": code,
            "current_password": DEFAULT_PASSWORD,
            "user_id": uid + 1000,
        },
    )
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "INVALID_PARAM"
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 6. 邮箱格式非法 ⇒ 422（字段级 INVALID_FORMAT）
# ══════════════════════════════════════════════════════════════════
def test_confirm_invalid_email_format(client):
    _, uid, token = register_token(client)
    _, code = _start_bind(client, token, unique_email())

    resp = req_confirm_bind(client, token, "not-an-email", code)
    assert resp.status_code == 422
    payload = resp.get_json()
    assert payload["code"] == "VALIDATION_FAILED"
    assert payload["errors"][0]["field"] == "email"
    assert payload["errors"][0]["code"] == "INVALID_FORMAT"
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 7. 错误验证码 ⇒ 中性 422（attempt_count ＋1）
# ══════════════════════════════════════════════════════════════════
def test_confirm_wrong_code_is_neutral_422(client):
    _, uid, token = register_token(client)
    email, code = _start_bind(client, token, unique_email())
    wrong = "000000" if code != "000000" else "111111"

    resp = req_confirm_bind(client, token, email, wrong)
    assert resp.status_code == 422
    payload = resp.get_json()
    assert payload["code"] == "VALIDATION_FAILED"
    assert payload["errors"][0]["field"] == "code"
    assert payload["errors"][0]["message"] == INVALID_CODE_MESSAGE
    # 中性：文案不区分「码错 / 过期 / 从未申请」
    assert "过期" in INVALID_CODE_MESSAGE and "不正确" in INVALID_CODE_MESSAGE
    assert one(
        "SELECT attempt_count FROM verification_code WHERE user_id=:u AND consumed_at IS NULL",
        u=uid,
    ) == 1
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 8. 过期验证码 ⇒ 中性 422（不消耗尝试次数）
# ══════════════════════════════════════════════════════════════════
def test_confirm_expired_code_is_neutral_422(client):
    _, uid, token = register_token(client)
    email, code = _start_bind(client, token, unique_email())

    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(NOW(), INTERVAL 40 MINUTE), "
        "expires_at = DATE_SUB(NOW(), INTERVAL 25 MINUTE) WHERE user_id=:u",
        u=uid,
    )
    resp = req_confirm_bind(client, token, email, code)
    assert resp.status_code == 422
    assert resp.get_json()["errors"][0]["message"] == INVALID_CODE_MESSAGE
    assert one(
        "SELECT attempt_count FROM verification_code WHERE user_id=:u", u=uid
    ) == 0
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 9. 尝试次数达上限 ⇒ 429；码作废；再试中性 422
# ══════════════════════════════════════════════════════════════════
def test_confirm_attempt_limit_aborts_challenge(client):
    _, uid, token = register_token(client)
    email, code = _start_bind(client, token, unique_email())
    wrong = "000000" if code != "000000" else "111111"

    statuses = [
        req_confirm_bind(client, token, email, wrong).status_code
        for _ in range(CODE_MAX_ATTEMPTS)
    ]
    assert statuses[: CODE_MAX_ATTEMPTS - 1] == [422] * (CODE_MAX_ATTEMPTS - 1), statuses
    assert statuses[-1] == 429, statuses

    # 该码已作废（consumed），尝试计数达上限
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 0
    assert one("SELECT attempt_count FROM verification_code WHERE user_id=:u", u=uid) == CODE_MAX_ATTEMPTS

    # 再试（无论对错）⇒ 中性 422（无有效挑战）
    after = req_confirm_bind(client, token, email, code)
    assert after.status_code == 422
    assert after.get_json()["errors"][0]["message"] == INVALID_CODE_MESSAGE
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None


# ══════════════════════════════════════════════════════════════════
# 10. 同一码重放 ⇒ 中性 422，不产生第二次绑定
# ══════════════════════════════════════════════════════════════════
def test_confirm_is_single_use_no_replay(client):
    _, uid, token = register_token(client)
    email = unique_email()
    _, code = _start_bind(client, token, email)

    assert req_confirm_bind(client, token, email, code).status_code == 200
    replay = req_confirm_bind(client, token, email, code)
    assert replay.status_code == 422
    assert replay.get_json()["errors"][0]["message"] == INVALID_CODE_MESSAGE
    # 绑定结果未被第二次改写
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == email


# ══════════════════════════════════════════════════════════════════
# 11. 并发两次 confirm ⇒ 恰好 1 次成功（行锁 ＋ 唯一索引）
# ══════════════════════════════════════════════════════════════════
def test_confirm_concurrent_only_one_succeeds(app, client):
    _, uid, token = register_token(client)
    email = unique_email()
    _, code = _start_bind(client, token, email)

    barrier = threading.Barrier(2)
    results = {}

    def _worker(idx: int) -> None:
        cli = app.test_client()
        try:
            barrier.wait(timeout=10)
            r = cli.post(
                f"{API}/auth/email/bind-confirm",
                headers=auth_header(token),
                json={"email": email, "code": code, "current_password": DEFAULT_PASSWORD},
            )
            results[idx] = r.status_code
        except Exception as exc:  # noqa: BLE001
            results[idx] = f"EXC:{type(exc).__name__}"

    threads = [threading.Thread(target=_worker, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    statuses = sorted(str(results.get(i)) for i in (0, 1))
    # 恰好一次成功；另一次必须是「无有效挑战」的中性 422
    assert statuses.count("200") == 1, statuses
    assert statuses.count("422") == 1, statuses
    # 账号只被绑定一次，且 email 正确
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == email
    assert one(
        "SELECT COUNT(*) FROM user_account WHERE id=:u AND email_verified_at IS NOT NULL", u=uid
    ) == 1


# ══════════════════════════════════════════════════════════════════
# 12. 邮箱唯一冲突 ⇒ 409 EMAIL_TAKEN ＋ 整事务回滚（无半写入）
# ══════════════════════════════════════════════════════════════════
def test_confirm_email_taken_409_and_full_rollback(client):
    # A 先占用该邮箱（真实契约）
    _, _, token_a = register_token(client)
    taken = unique_email("taken")
    bind_email_via_api(client, token_a, taken)

    # B 为同一邮箱发起并确认
    _, uid_b, token_b = register_token(client)
    _, code_b = _start_bind(client, token_b, taken)
    resp = req_confirm_bind(client, token_b, taken, code_b)
    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert resp.get_json()["code"] == "EMAIL_TAKEN"
    assert resp.get_json()["message"] == "该邮箱已被其他账号使用，请更换"

    # ★ 无半写入：B 的 email / email_verified_at 仍为 NULL
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid_b) is None
    assert one("SELECT email_verified_at FROM user_account WHERE id=:u", u=uid_b) is None
    # A 的占用不受影响
    assert one("SELECT COUNT(*) FROM user_account WHERE email=:e", e=taken) == 1


# ══════════════════════════════════════════════════════════════════
# 13. 大小写 / 空白归一后的唯一冲突 ⇒ 409
# ══════════════════════════════════════════════════════════════════
def test_confirm_email_taken_case_insensitive(client):
    _, _, token_a = register_token(client)
    base = unique_email("case")
    bind_email_via_api(client, token_a, base)  # 落库为小写规范形

    _, uid_b, token_b = register_token(client)
    # B 用大小写 + 空白变体（规范化后 == base）
    variant = "  " + base.upper() + "  "
    _, code_b = _start_bind(client, token_b, variant)
    resp = req_confirm_bind(client, token_b, variant, code_b)
    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert resp.get_json()["code"] == "EMAIL_TAKEN"
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid_b) is None


# ══════════════════════════════════════════════════════════════════
# 14. 码与邮箱绑定：为 A 邮箱申请的码不能用于绑定 B 邮箱
# ══════════════════════════════════════════════════════════════════
def test_confirm_code_is_bound_to_requested_email(client):
    _, uid, token = register_token(client)
    email_a = unique_email("bindto")
    email_b = unique_email("other")
    _, code_a = _start_bind(client, token, email_a)

    # 用 email_a 的码去确认 email_b ⇒ 中性 422（未被证明对 email_b 的控制权）
    wrong = req_confirm_bind(client, token, email_b, code_a)
    assert wrong.status_code == 422
    assert wrong.get_json()["errors"][0]["message"] == INVALID_CODE_MESSAGE
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None

    # 换成正确的目标邮箱 ⇒ 成功
    assert req_confirm_bind(client, token, email_a, code_a).status_code == 200
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == email_a


# ══════════════════════════════════════════════════════════════════
# 15. 绑定成功后**会话保留**（§Q-B3-11）
# ══════════════════════════════════════════════════════════════════
def test_bind_success_keeps_session_alive(client):
    username, uid, token = register_token(client)
    before = one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    )

    bind_email_via_api(client, token, unique_email())

    after = one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    )
    assert after == before, "邮箱绑定不得撤销任何会话（Q-B3-11）"
    # 原 Access Token 依旧可用（访问 A-06）
    me = client.get(f"{API}/users/me", headers=auth_header(token))
    assert me.status_code == 200, me.get_data(as_text=True)
    assert me.get_json()["data"]["username"] == username


# ══════════════════════════════════════════════════════════════════
# 16. 契约边界
# ══════════════════════════════════════════════════════════════════
def test_confirm_contract_boundaries(client):
    _, _, token = register_token(client)
    hdr = {"Authorization": f"Bearer {token}"}

    no_json = client.post(f"{API}/auth/email/bind-confirm", headers=hdr, data="x")
    assert no_json.status_code == 400
    assert no_json.get_json()["code"] == "INVALID_PARAM"

    missing_code = client.post(
        f"{API}/auth/email/bind-confirm",
        headers=hdr,
        json={"email": unique_email(), "current_password": DEFAULT_PASSWORD},
    )
    assert missing_code.status_code == 400
    assert missing_code.get_json()["errors"][0]["field"] == "code"

    missing_pwd = client.post(
        f"{API}/auth/email/bind-confirm",
        headers=hdr,
        json={"email": unique_email(), "code": "123456"},
    )
    assert missing_pwd.status_code == 400
    assert missing_pwd.get_json()["errors"][0]["field"] == "current_password"
    assert mail_service.memory_outbox() == []
