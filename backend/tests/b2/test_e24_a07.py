# -*- coding: utf-8 -*-
"""B2 · E-24 收口（A-05 改密作废旧重置凭证）＋ A-07 删除顺序 8 → 10。

需求方授权：
- §八 E-24：A-05 正常改密成功后，必须同时作废该账号尚未消费的 password reset credentials；
  **只做最小必要修改**，A-05 的原密码验证 / policy / bcrypt / Session revoke / 响应契约 / 错误码**全不变**。
- §九 A-07：``DELETE_ORDER`` 8 → 10，**只加入** ``verification_code`` 与 ``password_reset_token``；
  保持原删除语义；0 外键 ⇒ 不虚构 FK。
"""
from __future__ import annotations

from app.core.errors import ErrorCode
from app.core.password_reset import hash_reset_token
from app.services.account_service import DELETE_ORDER

from tests.b2.conftest import (
    API,
    DEFAULT_PASSWORD,
    NEW_PASSWORD,
    access_token_of,
    auth_header,
    latest_code_for,
    one,
    register_with_email,
    req_confirm,
    req_reset,
    req_verify,
)


def _obtain_token(client, username: str, email: str) -> str:
    req_reset(client, username)
    code = latest_code_for(email)
    assert code is not None
    resp = req_verify(client, username, code)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["data"]["reset_token"]


# ══════════════════════════════════════════════════════════════════
# E-24 ①：A-05 改密成功 ⇒ 未消费 reset 凭证立即失效
# ══════════════════════════════════════════════════════════════════
def test_e24_change_password_revokes_outstanding_reset_tokens(client):
    username, uid, email = register_with_email(client)
    token = _obtain_token(client, username, email)
    token_hash = hash_reset_token(token)
    assert one(
        "SELECT revoked_at IS NULL AND consumed_at IS NULL FROM password_reset_token "
        "WHERE token_hash=:h",
        h=token_hash,
    ) == 1

    # A-05 改密（拿到一个有效 Access Token）
    bear = access_token_of(client, username)
    resp = client.put(
        f"{API}/auth/password",
        headers=auth_header(bear),
        json={
            "old_password": DEFAULT_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # 旧凭证已**作废**（revoked，不是 consumed）
    assert one(
        "SELECT revoked_at IS NOT NULL FROM password_reset_token WHERE token_hash=:h", h=token_hash
    ) == 1
    assert one(
        "SELECT consumed_at IS NULL FROM password_reset_token WHERE token_hash=:h", h=token_hash
    ) == 1

    # 该凭证**再也换不到新密码**（E-24 要闭合的窗口）
    replay = req_confirm(client, token, new_password="hijacked777")
    assert replay.status_code == 401
    # 密码仍是 A-05 设的那个
    assert client.post(
        f"{API}/auth/login", json={"username": username, "password": NEW_PASSWORD}
    ).status_code == 200
    assert client.post(
        f"{API}/auth/login", json={"username": username, "password": "hijacked777"}
    ).status_code == 401


def test_e24_change_password_is_scoped_to_own_account(client):
    """E-24 只作废**本账号**的凭证，不越界影响别人。"""
    user_a, uid_a, email_a = register_with_email(client)
    user_b, uid_b, email_b = register_with_email(client)
    token_b = _obtain_token(client, user_b, email_b)

    bear = access_token_of(client, user_a)
    assert client.put(
        f"{API}/auth/password",
        headers=auth_header(bear),
        json={
            "old_password": DEFAULT_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    ).status_code == 200

    # B 的凭证**依然有效**
    assert one(
        "SELECT revoked_at IS NULL AND consumed_at IS NULL FROM password_reset_token "
        "WHERE token_hash=:h",
        h=hash_reset_token(token_b),
    ) == 1
    assert req_confirm(client, token_b, new_password="bbbbpass11").status_code == 200


# ══════════════════════════════════════════════════════════════════
# E-24 ②：A-05 既有行为**零回归**
# ══════════════════════════════════════════════════════════════════
def test_e24_a05_existing_behaviour_unchanged(client):
    username, uid, email = register_with_email(client)

    # ① 原密码错误 ⇒ 422 PASSWORD_INVALID（不是 401 / 不是 429）
    bear = access_token_of(client, username)
    bad = client.put(
        f"{API}/auth/password",
        headers=auth_header(bear),
        json={
            "old_password": "wrongpass1",
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert bad.status_code == 422
    assert bad.get_json()["code"] == ErrorCode.PASSWORD_INVALID

    # ② 弱密码 ⇒ 422 WEAK_PASSWORD，且不消耗「原密码连错」计数
    weak = client.put(
        f"{API}/auth/password",
        headers=auth_header(bear),
        json={"old_password": DEFAULT_PASSWORD, "new_password": "a1", "confirm_password": "a1"},
    )
    assert weak.status_code == 422
    assert weak.get_json()["code"] == ErrorCode.VALIDATION_FAILED

    # ③ 同会话原密码连错 5 次 ⇒ 429 SESSION_VERIFY_ABORTED（既有冻结行为）
    bear2 = access_token_of(client, username)
    statuses = []
    for _ in range(5):
        statuses.append(
            client.put(
                f"{API}/auth/password",
                headers=auth_header(bear2),
                json={
                    "old_password": "wrongpass1",
                    "new_password": NEW_PASSWORD,
                    "confirm_password": NEW_PASSWORD,
                },
            ).status_code
        )
    assert statuses[:4] == [422] * 4, statuses
    assert statuses[4] == 429, statuses

    # ④ 成功路径的响应契约与失效语义不变
    bear3 = access_token_of(client, username)
    ok = client.put(
        f"{API}/auth/password",
        headers=auth_header(bear3),
        json={
            "old_password": DEFAULT_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert ok.status_code == 200
    assert ok.get_json()["message"] == "密码已修改，请重新登录"
    assert set(ok.get_json()["data"].keys()) == {"all_sessions_revoked", "revoked_sessions"}
    assert ok.get_json()["data"]["all_sessions_revoked"] is True
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL", u=uid
    ) == 0
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_reason='password_changed'",
        u=uid,
    ) >= 1


# ══════════════════════════════════════════════════════════════════
# A-07 ①：DELETE_ORDER 恰 10 项，新增两表在 user_account 之前
# ══════════════════════════════════════════════════════════════════
def test_a07_delete_order_expanded_to_ten():
    assert len(DELETE_ORDER) == 10, DELETE_ORDER
    assert DELETE_ORDER == (
        "record_tag",
        "health_record",
        "health_goal",
        "user_profile",
        "export_job",
        "user_session",
        "login_failure_state",
        "verification_code",
        "password_reset_token",
        "user_account",
    )
    # 原 6 张相对顺序未变；账号仍在最后
    assert DELETE_ORDER.index("user_account") == len(DELETE_ORDER) - 1
    assert set(DELETE_ORDER) == {
        "record_tag",
        "health_record",
        "health_goal",
        "user_profile",
        "export_job",
        "user_session",
        "login_failure_state",
        "user_account",
        "verification_code",
        "password_reset_token",
    }


# ══════════════════════════════════════════════════════════════════
# A-07 ②：注销能清理新增的两张安全数据表
# ══════════════════════════════════════════════════════════════════
def test_a07_close_account_purges_new_security_tables(client):
    username, uid, email = register_with_email(client)
    # 造出两张新表的真实数据
    token = _obtain_token(client, username, email)
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 1
    assert one("SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u", u=uid) == 1
    assert token

    bear = access_token_of(client, username)
    resp = client.delete(
        f"{API}/users/me",
        headers=auth_header(bear),
        json={"password": DEFAULT_PASSWORD, "confirm_text": "注销账号"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["message"] == "账号已注销"
    assert resp.get_json()["data"] == {"account_closed": True}

    # 10 张表该账号的数据**全部归零**（含两张新表）
    for table, col in (
        ("user_account", "id"),
        ("user_profile", "user_id"),
        ("user_session", "user_id"),
        ("health_record", "user_id"),
        ("record_tag", "user_id"),
        ("health_goal", "user_id"),
        ("export_job", "user_id"),
        ("verification_code", "user_id"),
        ("password_reset_token", "user_id"),
    ):
        left = int(one(f"SELECT COUNT(*) FROM `{table}` WHERE `{col}`=:u", u=uid) or 0)
        assert left == 0, f"{table} 仍有残留 {left} 行"
    assert int(
        one("SELECT COUNT(*) FROM login_failure_state WHERE username=:n", n=username) or 0
    ) == 0

    # 注销后旧 Access Token 必然失效（幂等路径）
    again = client.delete(
        f"{API}/users/me",
        headers=auth_header(bear),
        json={"password": DEFAULT_PASSWORD, "confirm_text": "注销账号"},
    )
    assert again.status_code == 401


# ══════════════════════════════════════════════════════════════════
# A-07 ③：原有删除行为零回归（T0 三重确认）
# ══════════════════════════════════════════════════════════════════
def test_a07_existing_confirmation_behaviour_unchanged(client):
    username, uid, email = register_with_email(client)
    bear = access_token_of(client, username)

    # ① 确认文字不正确 ⇒ 422 INVALID_FORMAT
    wrong_text = client.delete(
        f"{API}/users/me",
        headers=auth_header(bear),
        json={"password": DEFAULT_PASSWORD, "confirm_text": "确认删除"},
    )
    assert wrong_text.status_code == 422
    assert wrong_text.get_json()["code"] == ErrorCode.VALIDATION_FAILED
    assert wrong_text.get_json()["errors"][0]["field"] == "confirm_text"
    assert wrong_text.get_json()["errors"][0]["code"] == "INVALID_FORMAT"

    # ② 确认文字缺失 ⇒ 422 REQUIRED
    missing_text = client.delete(
        f"{API}/users/me", headers=auth_header(bear), json={"password": DEFAULT_PASSWORD}
    )
    assert missing_text.status_code == 422
    assert missing_text.get_json()["errors"][0]["code"] == "REQUIRED"

    # ③ 密码错误 ⇒ 422 PASSWORD_INVALID（不锁定、不 429）
    wrong_pwd = client.delete(
        f"{API}/users/me",
        headers=auth_header(bear),
        json={"password": "wrongpass1", "confirm_text": "注销账号"},
    )
    assert wrong_pwd.status_code == 422
    assert wrong_pwd.get_json()["code"] == ErrorCode.PASSWORD_INVALID

    # ④ 账号仍然存在（失败路径无副作用）
    assert one("SELECT COUNT(*) FROM user_account WHERE id=:u", u=uid) == 1

    # ⑤ 未登录 ⇒ 401
    anon = client.delete(
        f"{API}/users/me", json={"password": DEFAULT_PASSWORD, "confirm_text": "注销账号"}
    )
    assert anon.status_code == 401
