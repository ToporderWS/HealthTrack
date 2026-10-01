# -*- coding: utf-8 -*-
"""B2 · PR-03 使用重置凭证设置新密码
（``POST /api/v1/auth/password-reset/confirm``）。

覆盖需求方 §十二「PR-03」11 项：正常重置 / token 错误 / 过期 / consumed / 重放 /
password policy / bcrypt / **Session 全撤销** / ``revoked_reason=password_reset`` /
其他 reset token 失效 / verification code 失效。
"""
from __future__ import annotations

import re

from app.core.password_reset import hash_reset_token
from app.core.security import verify_password

from tests.b2.conftest import (
    API,
    DEFAULT_PASSWORD,
    NEW_PASSWORD,
    exec_sql,
    latest_code_for,
    one,
    req_confirm,
    register_with_email,
    req_reset,
    req_verify,
)

BCRYPT = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")


def _obtain_token(client, username: str, email: str) -> str:
    """走完 PR-01 + PR-02，拿到一次性 reset_token。

    PR-01 有 60 秒**服务端重发冷却**（冻结值 ``RESEND_COOLDOWN_SECONDS``）：
    冷却期内的重复请求会被统一 200 **静默吞掉**（不发新码）⇒ 同账号连续取码
    只能拿到"已被上一次校验消费掉"的旧码。故本装置在取码前把该账号既有验证码
    的 ``created_at`` 回拨 120 秒以解除冷却。

    **这只是测试装置技巧，不是产品语义**：冷却行为本身由
    ``tests/b2/test_pr01_request.py`` 独立覆盖；此处与
    ``test_confirm_revokes_other_outstanding_credentials`` 的做法一致。
    """
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id = (SELECT id FROM user_account WHERE username = :u)",
        u=username,
    )
    req_reset(client, username)
    code = latest_code_for(email)
    assert code is not None
    resp = req_verify(client, username, code)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["data"]["reset_token"]


def _login(client, username: str, password: str):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


# ══════════════════════════════════════════════════════════════════
# 1. 正常重置（含失效矩阵）
# ══════════════════════════════════════════════════════════════════
def test_confirm_resets_password_and_invalidates_everything(client):
    username, uid, email = register_with_email(client)
    # 制造 3 条有效会话（注册自动登录 1 ＋ 再登录 2）
    assert _login(client, username, DEFAULT_PASSWORD).status_code == 200
    assert _login(client, username, DEFAULT_PASSWORD).status_code == 200
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    ) == 3

    token = _obtain_token(client, username, email)
    resp = req_confirm(client, token)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["code"] == "OK"
    assert body["message"] == "密码已重置，请使用新密码登录"
    assert body["data"] == {"all_sessions_revoked": True, "revoked_sessions": 3}

    # ③ 全部会话被撤销，且 reason = password_reset
    # （必须在下方「用新密码登录」**之前**校验：那次登录会为账号新建 1 条有效
    #   会话，它由本用例自身产生，不应计入「重置前会话是否全部撤销」的判据。）
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    ) == 0
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_reason='password_reset'",
        u=uid,
    ) == 3

    # ① 新密码生效（可登录）；旧密码失效
    assert _login(client, username, NEW_PASSWORD).status_code == 200
    assert _login(client, username, DEFAULT_PASSWORD).status_code == 401

    # ② 密码按既有 bcrypt 策略保存
    new_hash = one("SELECT password_hash FROM user_account WHERE id=:u", u=uid)
    assert BCRYPT.match(str(new_hash))
    assert len(str(new_hash)) == 60
    assert verify_password(NEW_PASSWORD, str(new_hash)) is True
    assert one("SELECT password_algo FROM user_account WHERE id=:u", u=uid) == "bcrypt"

    # ④ 该凭证已**消费**（一次性）
    assert one(
        "SELECT consumed_at IS NOT NULL FROM password_reset_token WHERE token_hash=:h",
        h=hash_reset_token(token),
    ) == 1

    # ⑤ 该账号未消费验证码全部失效
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 0


# ══════════════════════════════════════════════════════════════════
# 2. token 错误 / 不存在 / 空前缀 ⇒ 401（中性文案）
# ══════════════════════════════════════════════════════════════════
def test_confirm_invalid_token_is_neutral_401(client):
    username, uid, email = register_with_email(client)
    _obtain_token(client, username, email)

    for bad in ("not-a-real-token", "", "x" * 64):
        resp = req_confirm(client, bad)
        assert resp.status_code == 401, (bad, resp.get_data(as_text=True))
        assert resp.get_json()["code"] == "UNAUTHENTICATED"
    # 密码未被改动
    assert verify_password(DEFAULT_PASSWORD, one(
        "SELECT password_hash FROM user_account WHERE id=:u", u=uid
    )) is True


# ══════════════════════════════════════════════════════════════════
# 3. token 过期 ⇒ 401（且不改密码）
# ══════════════════════════════════════════════════════════════════
def test_confirm_expired_token_rejected(client):
    username, uid, email = register_with_email(client)
    token = _obtain_token(client, username, email)

    exec_sql(
        "UPDATE password_reset_token SET created_at = DATE_SUB(NOW(), INTERVAL 40 MINUTE), "
        "expires_at = DATE_SUB(NOW(), INTERVAL 25 MINUTE) WHERE user_id=:u",
        u=uid,
    )
    resp = req_confirm(client, token)
    assert resp.status_code == 401
    assert verify_password(DEFAULT_PASSWORD, one(
        "SELECT password_hash FROM user_account WHERE id=:u", u=uid
    )) is True
    # 会话未被撤销（失败不产生副作用）
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    ) == 1


# ══════════════════════════════════════════════════════════════════
# 4. token 重放（第二次使用）⇒ 401
# ══════════════════════════════════════════════════════════════════
def test_confirm_token_is_single_use_no_replay(client):
    username, uid, email = register_with_email(client)
    token = _obtain_token(client, username, email)

    assert req_confirm(client, token, new_password="firstone11").status_code == 200
    replay = req_confirm(client, token, new_password="secondone22")
    assert replay.status_code == 401
    assert replay.get_json()["code"] == "UNAUTHENTICATED"

    # 仍是第一次设置的密码
    assert _login(client, username, "firstone11").status_code == 200
    assert _login(client, username, "secondone22").status_code == 401


# ══════════════════════════════════════════════════════════════════
# 5. 密码规则（复用既有统一 policy；不另立一套）
# ══════════════════════════════════════════════════════════════════
def test_confirm_password_policy_reused(client):
    username, uid, email = register_with_email(client)

    # ① 太短
    t1 = _obtain_token(client, username, email)
    r1 = req_confirm(client, t1, new_password="a1")
    assert r1.status_code == 422
    assert r1.get_json()["code"] == "VALIDATION_FAILED"
    assert r1.get_json()["errors"][0]["field"] == "new_password"
    assert r1.get_json()["errors"][0]["code"] == "WEAK_PASSWORD"

    # ② 缺数字
    t2 = _obtain_token(client, username, email)
    r2 = req_confirm(client, t2, new_password="abcdefgh")
    assert r2.status_code == 422
    assert r2.get_json()["errors"][0]["code"] == "WEAK_PASSWORD"

    # ③ 含空格
    t3 = _obtain_token(client, username, email)
    r3 = req_confirm(client, t3, new_password="abc 12345")
    assert r3.status_code == 422
    assert r3.get_json()["errors"][0]["code"] == "WEAK_PASSWORD"

    # ④ 两次不一致
    t4 = _obtain_token(client, username, email)
    r4 = req_confirm(client, t4, new_password="validpass99", confirm="different99")
    assert r4.status_code == 422
    codes = {e["code"] for e in r4.get_json()["errors"]}
    assert "MISMATCH" in codes

    # ⑤ 与当前密码相同
    t5 = _obtain_token(client, username, email)
    r5 = req_confirm(client, t5, new_password=DEFAULT_PASSWORD)
    assert r5.status_code == 422
    assert {e["code"] for e in r5.get_json()["errors"]} == {"SAME_AS_OLD"}

    # ⑥ 合规密码通过
    t6 = _obtain_token(client, username, email)
    assert req_confirm(client, t6, new_password=NEW_PASSWORD).status_code == 200


# ══════════════════════════════════════════════════════════════════
# 6. 密码规则校验失败 ⇒ **不消费**凭证（用户可重试）
# ══════════════════════════════════════════════════════════════════
def test_confirm_policy_failure_does_not_consume_token(client):
    username, uid, email = register_with_email(client)
    token = _obtain_token(client, username, email)

    assert req_confirm(client, token, new_password="a1").status_code == 422
    assert one(
        "SELECT consumed_at IS NULL AND revoked_at IS NULL FROM password_reset_token "
        "WHERE token_hash=:h",
        h=hash_reset_token(token),
    ) == 1
    # 仍可用它成功重置
    assert req_confirm(client, token, new_password=NEW_PASSWORD).status_code == 200


# ══════════════════════════════════════════════════════════════════
# 7. 成功重置 ⇒ 该账号**其余**未消费凭证全部作废
# ══════════════════════════════════════════════════════════════════
def test_confirm_revokes_other_outstanding_credentials(client):
    username, uid, email = register_with_email(client)
    token_a = _obtain_token(client, username, email)
    # 再拿一条（绕过冷却）
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u",
        u=uid,
    )
    token_b = _obtain_token(client, username, email)
    assert token_a != token_b

    assert req_confirm(client, token_b, new_password=NEW_PASSWORD).status_code == 200

    # token_a 已作废（revoked，未消费）
    assert one(
        "SELECT revoked_at IS NOT NULL FROM password_reset_token WHERE token_hash=:h",
        h=hash_reset_token(token_a),
    ) == 1
    # 用 token_a 走 PR-03 ⇒ 401
    assert req_confirm(client, token_a, new_password="another123").status_code == 401


# ══════════════════════════════════════════════════════════════════
# 8. 成功重置后重置的凭证不能再换取新密码（终态一致）
# ══════════════════════════════════════════════════════════════════
def test_confirm_end_state_is_consistent(client):
    username, uid, email = register_with_email(client)
    token = _obtain_token(client, username, email)
    assert req_confirm(client, token, new_password=NEW_PASSWORD).status_code == 200

    # 该账号没有任何"可能再改一次密码"的残留凭证
    assert one(
        "SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u "
        "AND consumed_at IS NULL AND revoked_at IS NULL",
        u=uid,
    ) == 0
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 0
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    ) == 0


# ══════════════════════════════════════════════════════════════════
# 9. 契约边界
# ══════════════════════════════════════════════════════════════════
def test_confirm_contract_boundaries(client):
    no_json = client.post(f"{API}/auth/password-reset/confirm", data="x")
    assert no_json.status_code == 400

    missing = client.post(
        f"{API}/auth/password-reset/confirm", json={"new_password": "validpass99"}
    )
    assert missing.status_code == 400
    assert missing.get_json()["errors"][0]["field"] == "reset_token"

    with_uid = client.post(
        f"{API}/auth/password-reset/confirm",
        json={
            "reset_token": "x",
            "new_password": "validpass99",
            "confirm_password": "validpass99",
            "user_id": 5,
        },
    )
    assert with_uid.status_code == 400
    assert with_uid.get_json()["code"] == "INVALID_PARAM"


# ══════════════════════════════════════════════════════════════════
# 10. 错误码：**B2 自身净增 0**；B3（授权 §Q-B3-03）追加 ``EMAIL_TAKEN`` 1 个 ⇒ 共 19
# ══════════════════════════════════════════════════════════════════
def test_confirm_uses_only_existing_error_codes(client):
    from app.core.errors import ERROR_HTTP_STATUS, ErrorCode, FieldErrorCode

    frozen = set(ERROR_HTTP_STATUS.keys())
    # 18（S1-B 冻结）＋ 1（B3 授权 §Q-B3-03 追加 ``EMAIL_TAKEN``）= 19。
    # 本用例原意「B2 自身**未新增**任何错误码」：除 B3 授权新增的那 1 个外，
    # 回填的冻结集合必须与之完全相等 ⇒ 任何「表外码」仍会在此处被抓出。
    assert len(frozen) == 19, f"全局错误码应为 19 个（18 冻结 ＋ B3 追加 1），实测 {len(frozen)}"

    username, uid, email = register_with_email(client)
    token = _obtain_token(client, username, email)

    observed = set()
    observed.add(req_confirm(client, "bad-token").get_json()["code"])
    observed.add(
        req_confirm(client, token, new_password="a1").get_json()["code"]
    )
    assert observed <= frozen, f"出现未登记错误码：{observed - frozen}"

    field_codes = {
        FieldErrorCode.REQUIRED,
        FieldErrorCode.INVALID_TYPE,
        FieldErrorCode.INVALID_FORMAT,
        FieldErrorCode.WEAK_PASSWORD,
        FieldErrorCode.MISMATCH,
        FieldErrorCode.SAME_AS_OLD,
        FieldErrorCode.NOT_ACCEPTED,
    }
    assert ErrorCode.UNAUTHENTICATED in frozen
    assert ErrorCode.SESSION_VERIFY_ABORTED in frozen
    assert FieldErrorCode.SAME_AS_OLD in field_codes
