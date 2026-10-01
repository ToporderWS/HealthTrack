# -*- coding: utf-8 -*-
"""B2 · PR-02 校验验证码并签发一次性重置凭证
（``POST /api/v1/auth/password-reset/verify``）。

覆盖需求方 §十二「PR-02」10 项：正确 / 错误 / attempt_count / 超限 / 过期 /
consumed / purpose 错误 / user mismatch / **reset token 原文不入库** / 重复验证。
外加「错误码与文案不造成额外账号枚举面」。
"""
from __future__ import annotations

import re

from sqlalchemy import text

from app.core.db import get_engine
from app.core.password_reset import (
    CODE_MAX_ATTEMPTS,
    RESET_TOKEN_TTL_MINUTES,
    hash_reset_token,
)
from app.services import mail_service

from tests.b2.conftest import (
    API,
    exec_sql,
    latest_code_for,
    one,
    register_with_email,
    req_reset,
    req_verify,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
INVALID_MSG = "验证码不正确或已过期"


def _issue_code(client, email: str) -> str:
    """发一封码并返回明文（仅经内存投递载荷，DB 无明文）。"""
    return latest_code_for(email)


# ══════════════════════════════════════════════════════════════════
# 1. 正确验证码 ⇒ 200 + 一次性 reset_token（DB 只存 SHA-256）
# ══════════════════════════════════════════════════════════════════
def test_verify_correct_code_issues_reset_credential(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    code = _issue_code(client, email)

    resp = req_verify(client, username, code)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["code"] == "OK"
    assert body["message"] == "验证成功"
    token = body["data"]["reset_token"]
    assert isinstance(token, str) and len(token) >= 60
    assert body["data"]["expires_in"] == RESET_TOKEN_TTL_MINUTES * 60 == 900

    # 验证码已被消费
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NOT NULL", u=uid
    ) == 1

    # reset token 入库形态：**只存 SHA-256**，且与明文无关
    stored = one("SELECT token_hash FROM password_reset_token WHERE user_id=:u", u=uid)
    assert HEX64.match(str(stored))
    assert stored == hash_reset_token(token)
    assert stored != token

    # DB 全列扫描：没有任何列等于 reset_token 原文
    with get_engine().connect() as conn:
        cols = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='password_reset_token'"
                )
            ).all()
        ]
        assert "token" not in cols, "password_reset_token 出现了明文列"
        for col in cols:
            # ⚠️ CAST 成字符串再比较（DATETIME 列直接绑定长 token 会触发 MySQL 1525）。
            hit = int(
                conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM password_reset_token "
                        f"WHERE CAST(`{col}` AS CHAR) = :c"
                    ),
                    {"c": token},
                ).scalar()
                or 0
            )
            assert hit == 0, f"列 {col} 中出现了 reset_token 明文"


# ══════════════════════════════════════════════════════════════════
# 2. 错误验证码 ⇒ 422（唯一中性文案）＋ attempt_count +1
# ══════════════════════════════════════════════════════════════════
def test_verify_wrong_code_is_neutral_and_counts_attempt(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    good = _issue_code(client, email)
    wrong = "000000" if good != "000000" else "111111"

    resp = req_verify(client, username, wrong)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["errors"][0]["field"] == "code"
    assert body["errors"][0]["message"] == INVALID_MSG
    # 文案不得暗示账号状态
    for banned in ("不存在", "未绑定", "未注册", "没有该"):
        assert banned not in body["message"] + body["errors"][0]["message"]

    assert int(one("SELECT attempt_count FROM verification_code WHERE user_id=:u", u=uid)) == 1
    # 未消费、仍可用（正确码随后仍可通过）
    assert one(
        "SELECT consumed_at IS NULL FROM verification_code WHERE user_id=:u", u=uid
    ) == 1
    assert req_verify(client, username, good).status_code == 200


# ══════════════════════════════════════════════════════════════════
# 3. 超过最大尝试次数 ⇒ 429 且该码作废
# ══════════════════════════════════════════════════════════════════
def test_verify_exceeding_max_attempts_aborts_and_invalidates(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    good = _issue_code(client, email)
    wrong = "000000" if good != "000000" else "111111"

    statuses = [req_verify(client, username, wrong).status_code for _ in range(CODE_MAX_ATTEMPTS)]
    assert statuses[:-1] == [422] * (CODE_MAX_ATTEMPTS - 1), statuses
    assert statuses[-1] == 429, statuses

    # 达上限时该码已被**作废**（consumed）⇒ 再验时已无有效挑战码，
    # 故后续一律回到**中性 422**（与「从未申请 / 码错误」不可区分）。
    # 这是冻结口径「达上限即作废该码」的必然结果，**不是**产品缺陷；
    # 反而比「持续 429」更不易被用于探测锁定状态。
    last = req_verify(client, username, wrong)
    assert last.status_code == 422
    assert last.get_json()["errors"][0]["message"] == INVALID_MSG

    # 该码已作废（不可再用），**即使拿正确的码**也通不过
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 0
    assert req_verify(client, username, good).status_code == 422


# ══════════════════════════════════════════════════════════════════
# 4. 过期验证码 ⇒ 422
# ══════════════════════════════════════════════════════════════════
def test_verify_expired_code_rejected(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    code = _issue_code(client, email)

    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(NOW(), INTERVAL 40 MINUTE), "
        "expires_at = DATE_SUB(NOW(), INTERVAL 25 MINUTE) WHERE user_id=:u",
        u=uid,
    )
    resp = req_verify(client, username, code)
    assert resp.status_code == 422
    assert resp.get_json()["errors"][0]["message"] == INVALID_MSG
    # 过期不产生 reset token
    assert one("SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u", u=uid) == 0


# ══════════════════════════════════════════════════════════════════
# 5. 已消费的验证码 ⇒ 422（重复验证）
# ══════════════════════════════════════════════════════════════════
def test_verify_consumed_code_rejected_and_no_replay(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    code = _issue_code(client, email)

    assert req_verify(client, username, code).status_code == 200
    again = req_verify(client, username, code)
    assert again.status_code == 422
    assert again.get_json()["errors"][0]["message"] == INVALID_MSG
    # 只签发过 1 条凭证（重复验证不产生第二条）
    assert one("SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u", u=uid) == 1


# ══════════════════════════════════════════════════════════════════
# 6. purpose 错误（跨用途复用）⇒ 422
# ══════════════════════════════════════════════════════════════════
def test_verify_wrong_purpose_rejected(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    code = _issue_code(client, email)

    exec_sql("UPDATE verification_code SET purpose='email_bind' WHERE user_id=:u", u=uid)
    resp = req_verify(client, username, code)
    assert resp.status_code == 422
    assert resp.get_json()["errors"][0]["message"] == INVALID_MSG


# ══════════════════════════════════════════════════════════════════
# 7. user mismatch（A 的码拿到 B 上）⇒ 422（HMAC 绑定 user_id）
# ══════════════════════════════════════════════════════════════════
def test_verify_code_bound_to_user(client):
    user_a, uid_a, email_a = register_with_email(client)
    user_b, uid_b, email_b = register_with_email(client)

    req_reset(client, user_a)
    code_a = _issue_code(client, email_a)
    assert code_a is not None

    # 把 A 的码原样交给 B
    resp = req_verify(client, user_b, code_a)
    assert resp.status_code == 422
    assert resp.get_json()["errors"][0]["message"] == INVALID_MSG
    assert one("SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u", u=uid_b) == 0
    # A 的码不受影响（仍可用）
    assert req_verify(client, user_a, code_a).status_code == 200


# ══════════════════════════════════════════════════════════════════
# 8. 账号不存在 ⇒ 与"码错误"完全一致，且无额外枚举面
# ══════════════════════════════════════════════════════════════════
def test_verify_unknown_account_is_indistinguishable(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    good = _issue_code(client, email)

    wrong_existing = req_verify(client, username, "000000")
    unknown = req_verify(client, "nosuchuserzzz9", "000000")
    assert wrong_existing.status_code == unknown.status_code == 422
    assert wrong_existing.get_json()["code"] == unknown.get_json()["code"] == "VALIDATION_FAILED"
    assert (
        wrong_existing.get_json()["errors"] == unknown.get_json()["errors"]
    ), "存在/不存在账号的错误明细必须完全一致"
    assert good is not None


# ══════════════════════════════════════════════════════════════════
# 9. 成功签发新凭证 ⇒ 作废该账号此前未消费的旧凭证
# ══════════════════════════════════════════════════════════════════
def test_issuing_new_credential_revokes_previous(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    c1 = _issue_code(client, email)
    first = req_verify(client, username, c1).get_json()["data"]["reset_token"]

    # 再次走一遍：绕过冷却 → 发新码 → 验证
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u",
        u=uid,
    )
    req_reset(client, username)
    c2 = _issue_code(client, email)
    assert c2 is not None
    second = req_verify(client, username, c2).get_json()["data"]["reset_token"]
    assert second != first

    # 旧凭证被 revoked（不是 consumed）
    old_hash = hash_reset_token(first)
    assert one(
        "SELECT revoked_at IS NOT NULL FROM password_reset_token WHERE token_hash=:h", h=old_hash
    ) == 1
    assert one(
        "SELECT consumed_at IS NULL FROM password_reset_token WHERE token_hash=:h", h=old_hash
    ) == 1
    # 新凭证仍有效
    new_hash = hash_reset_token(second)
    assert one(
        "SELECT revoked_at IS NULL AND consumed_at IS NULL FROM password_reset_token "
        "WHERE token_hash=:h",
        h=new_hash,
    ) == 1


# ══════════════════════════════════════════════════════════════════
# 10. 契约边界
# ══════════════════════════════════════════════════════════════════
def test_verify_contract_boundaries(client):
    no_json = client.post(f"{API}/auth/password-reset/verify", data="x")
    assert no_json.status_code == 400

    missing_code = client.post(f"{API}/auth/password-reset/verify", json={"username": "abc1234"})
    assert missing_code.status_code == 400
    assert missing_code.get_json()["errors"][0]["field"] == "code"

    with_uid = client.post(
        f"{API}/auth/password-reset/verify",
        json={"username": "abc1234", "code": "123456", "user_id": 7},
    )
    assert with_uid.status_code == 400
    assert with_uid.get_json()["code"] == "INVALID_PARAM"

    # 未发起过任何找回 ⇒ 与"码错误"同响应
    fresh_user, _, _ = register_with_email(client)
    never = req_verify(client, fresh_user, "123456")
    assert never.status_code == 422
    assert never.get_json()["errors"][0]["message"] == INVALID_MSG


# ══════════════════════════════════════════════════════════════════
# 11. 不建立登录态（reset_token 不是 Access / Refresh Token）
# ══════════════════════════════════════════════════════════════════
def test_reset_credential_grants_no_login_state(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    code = _issue_code(client, email)
    token = req_verify(client, username, code).get_json()["data"]["reset_token"]

    # ① 不能被当作 Bearer 使用
    resp = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401

    # ② 不能被当作 refresh_token 使用
    resp2 = client.post(f"{API}/auth/refresh", json={"refresh_token": token})
    assert resp2.status_code == 401

    # ③ 不产生任何新的 user_session（只有注册时自动登录的那一条仍有效）
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    ) == 1
