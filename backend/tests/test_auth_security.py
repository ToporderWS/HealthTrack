# -*- coding: utf-8 -*-
"""B. 安全测试（13 项 + 5 项附加）—— 逐条对应 S1-A / S1-B / S1-D 冻结口径。

| 编号 | 用例 | 冻结依据 |
|---|---|---|
| B-1 | 数据库不保存明文密码 | S1-A §1 / S1-D §6.2 |
| B-2 | bcrypt cost = 12 | S1-D §6.2 |
| B-3 | 连错 5 次 → 锁 5 分钟 | S1-A §2 / S1-B §7.4 |
| B-4 | 24h 内二次 → 15 分钟 | 同上 |
| B-5 | 三次及以上 → 60 分钟（上限） | 同上 |
| B-6 | 锁定期间拒绝登录 | 同上 |
| B-7 | 登录成功清零失败状态 | 同上 |
| B-8 | 刷新令牌单次使用 | S1-D §6.1 |
| B-9 | 重放 → ``TOKEN_REUSED`` | S1-B A-03 |
| B-10 | 重放后全部会话失效 | S1-D §6.1 |
| B-11 | 改密后旧 Token 全失效 | S1-A §3 / S1-D §6.1 |
| B-12 | 请求携带 ``user_id`` → 400 | S1-D §6.3 |
| B-13 | 不泄露用户名存在性 | S1-A §2 / S1-B A-02 |
"""
from __future__ import annotations

from tests.conftest import (
    API,
    DEFAULT_PASSWORD,
    DEFAULT_PASSWORD2,
    account_row,
    auth_header,
    failure_state,
    force_unlock,
    login,
    register,
    rewind_first_fail,
    tokens_of,
    unique_username,
)


def _fail_login(client, username: str, times: int = 5):
    """连续 N 次错误密码；返回最后一次响应。"""
    resp = None
    for _ in range(times):
        resp = login(client, username, "wrongpw123")
    return resp


def _one_account(client):
    """注册一个账号，返回 ``(username, password, tokens)``。"""
    username, resp = register(client, unique_username())
    assert resp.status_code == 201, resp.get_json()
    return username, DEFAULT_PASSWORD, tokens_of(resp)


# ════════════════════════════════════════════════════════════════════
# B1 / B2 —— 密码存储
# ════════════════════════════════════════════════════════════════════
def test_b1_password_never_stored_in_plaintext(client):
    """B-1 只存哈希；响应体不回显密码或哈希。"""
    username, resp = register(client, unique_username())
    row = account_row(username)
    assert row is not None
    assert row["password_hash"] != DEFAULT_PASSWORD
    assert DEFAULT_PASSWORD not in row["password_hash"]
    assert row["password_hash"].startswith(("$2a$", "$2b$", "$2y$"))
    assert row["password_algo"] == "bcrypt"

    raw = resp.get_data(as_text=True)
    assert DEFAULT_PASSWORD not in raw
    assert row["password_hash"] not in raw


def test_b2_bcrypt_cost_is_12(client):
    """B-2 bcrypt cost = 12。"""
    username, _ = register(client, unique_username())
    assert account_row(username)["password_hash"].split("$")[2] == "12"


# ════════════════════════════════════════════════════════════════════
# B3 ~ B7 —— 登录失败锁定
# ════════════════════════════════════════════════════════════════════
def test_b3_lock_after_5_consecutive_failures(client):
    """B-3 前 4 次 401 ``CREDENTIALS_INVALID``；第 5 次锁定 5 分钟。"""
    username, _ = register(client, unique_username())

    for i in range(1, 5):
        resp = login(client, username, "wrongpw123")
        assert resp.status_code == 401, f"第 {i} 次失败应为 401"
        assert resp.get_json()["code"] == "CREDENTIALS_INVALID"

    fifth = login(client, username, "wrongpw123")
    assert fifth.status_code == 423
    body = fifth.get_json()
    assert body["code"] == "ACCOUNT_LOCKED"
    assert body["data"]["locked_minutes"] == 5

    state = failure_state(username)
    assert state["locked_until"] is not None
    assert state["lock_level"] == 1
    assert state["fail_count"] == 0        # 触发锁定后计数归零（S1-B §7.4）


def test_b4_lock_step_15_minutes(client):
    """B-4 24h 内第二次触发 → 15 分钟。"""
    username, _ = register(client, unique_username())
    assert _fail_login(client, username).get_json()["data"]["locked_minutes"] == 5

    force_unlock(username)                 # 模拟首次锁定到期
    second = _fail_login(client, username)
    assert second.status_code == 423
    assert second.get_json()["data"]["locked_minutes"] == 15
    assert failure_state(username)["lock_level"] == 2


def test_b5_lock_step_60_minutes_and_upper_bound(client):
    """B-5 三次及以上 → 60 分钟；**上限 60 分钟不再递增**。"""
    username, _ = register(client, unique_username())
    _fail_login(client, username)

    force_unlock(username)
    _fail_login(client, username)
    assert failure_state(username)["lock_level"] == 2

    force_unlock(username)
    third = _fail_login(client, username)
    assert third.get_json()["data"]["locked_minutes"] == 60
    assert failure_state(username)["lock_level"] == 3

    force_unlock(username)
    fourth = _fail_login(client, username)
    assert fourth.get_json()["data"]["locked_minutes"] == 60    # 仍为上限
    assert failure_state(username)["lock_level"] == 3


def test_b5b_lock_level_resets_after_24h_window(client):
    """B-5b 超出 24h 窗口 → 档位复位（重新从 5 分钟起）。"""
    username, _ = register(client, unique_username())
    _fail_login(client, username)
    force_unlock(username)
    _fail_login(client, username)
    assert failure_state(username)["lock_level"] == 2

    rewind_first_fail(username, hours=25)   # 窗口滚出 24h
    force_unlock(username)
    again = _fail_login(client, username)
    assert again.get_json()["data"]["locked_minutes"] == 5
    assert failure_state(username)["lock_level"] == 1


def test_b6_login_rejected_during_lock(client):
    """B-6 锁定期间即使密码正确也返回 423，仅告知剩余分钟。"""
    username, _ = register(client, unique_username())
    _fail_login(client, username)

    resp = login(client, username, DEFAULT_PASSWORD)
    assert resp.status_code == 423
    body = resp.get_json()
    assert body["code"] == "ACCOUNT_LOCKED"
    assert 1 <= body["data"]["locked_minutes"] <= 5
    assert body["message"].endswith("分钟后再试")


def test_b7_successful_login_clears_failure_state(client):
    """B-7 登录成功立即清零失败计数与锁定状态。"""
    username, _ = register(client, unique_username())
    for _ in range(4):                      # 4 次 < 阈值，不触发锁定
        login(client, username, "wrongpw123")
    assert failure_state(username)["fail_count"] == 4

    assert login(client, username, DEFAULT_PASSWORD).status_code == 200
    state = failure_state(username)
    assert state["fail_count"] == 0
    assert state["lock_level"] == 0
    assert state["locked_until"] is None
    assert state["first_fail_at"] is None


def test_b7b_failure_tracked_for_unknown_username(client):
    """B-7b 防账号枚举：**不存在的用户名同样落行计数**。"""
    ghost = unique_username("ghost")
    for _ in range(2):
        assert login(client, ghost, "wrongpw123").status_code == 401
    state = failure_state(ghost)
    assert state is not None and state["fail_count"] == 2


# ════════════════════════════════════════════════════════════════════
# B8 ~ B10 —— Refresh Token
# ════════════════════════════════════════════════════════════════════
def test_b8_refresh_token_single_use(client, new_account):
    """B-8 成功刷新后旧刷新令牌立即失效。"""
    _, _, tokens = new_account
    old = tokens["refresh_token"]
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": old}).status_code == 200
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": old}).status_code == 401


def test_b9_refresh_replay_returns_token_reused(client, new_account):
    """B-9 重放已消费的刷新令牌 → 401 ``TOKEN_REUSED``。"""
    _, _, tokens = new_account
    old = tokens["refresh_token"]
    client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    resp = client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "TOKEN_REUSED"


def test_b10_replay_revokes_all_sessions_of_user(client, new_account):
    """B-10 重放后该用户**全部会话**立即失效（其他设备一并掉线）。"""
    username, password, t1 = new_account
    t2 = tokens_of(login(client, username, password))            # 第二个设备
    # 刷新接口把 Token 对直接放在 data 下（契约 A-03）
    refresh_resp = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert refresh_resp.status_code == 200
    refreshed = refresh_resp.get_json()["data"]

    # 重放前：第二设备与刷新出的新 access 均可用
    assert client.get(f"{API}/users/me", headers=auth_header(t2["access_token"])).status_code == 200
    assert client.get(f"{API}/users/me", headers=auth_header(refreshed["access_token"])).status_code == 200

    replay = client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert replay.status_code == 401 and replay.get_json()["code"] == "TOKEN_REUSED"

    # 重放后：全部失效
    assert client.get(f"{API}/users/me", headers=auth_header(t2["access_token"])).status_code == 401
    assert client.get(f"{API}/users/me", headers=auth_header(refreshed["access_token"])).status_code == 401
    assert client.post(
        f"{API}/auth/refresh", json={"refresh_token": refreshed["refresh_token"]}
    ).status_code == 401


def test_b10b_refresh_invalid_token_or_missing_param(client):
    """B-10b 无效刷新令牌 → 401 ``UNAUTHENTICATED``；缺参数 → 400。"""
    resp = client.post(f"{API}/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401 and resp.get_json()["code"] == "UNAUTHENTICATED"
    assert client.post(f"{API}/auth/refresh", json={}).status_code == 400
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": ""}).status_code == 400


# ════════════════════════════════════════════════════════════════════
# B11 —— 改密后旧 Token 失效
# ════════════════════════════════════════════════════════════════════
def test_b11_change_password_invalidates_all_old_tokens(client, new_account):
    """B-11 改密成功后旧 Access / Refresh 全部失效（含当前设备）。"""
    username, password, t1 = new_account
    t2 = tokens_of(login(client, username, password))

    resp = client.put(
        f"{API}/auth/password",
        headers=auth_header(t1["access_token"]),
        json={"old_password": password, "new_password": DEFAULT_PASSWORD2,
              "confirm_password": DEFAULT_PASSWORD2},
    )
    assert resp.status_code == 200

    assert client.get(f"{API}/users/me", headers=auth_header(t1["access_token"])).status_code == 401
    assert client.get(f"{API}/users/me", headers=auth_header(t2["access_token"])).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401
    # 新密码可登录、旧密码不可登录
    assert login(client, username, password).status_code == 401
    assert login(client, username, DEFAULT_PASSWORD2).status_code == 200


def test_b11b_change_password_wrong_old_password_and_abort(client):
    """B-11b 原密码错误 → 422 ``PASSWORD_INVALID``；同一会话连错 5 次 → 429 中止。"""
    username, _, t = _one_account(client)
    header = auth_header(t["access_token"])
    payload = {"old_password": "badpw1234", "new_password": DEFAULT_PASSWORD2,
               "confirm_password": DEFAULT_PASSWORD2}

    for i in range(1, 5):
        resp = client.put(f"{API}/auth/password", headers=header, json=payload)
        assert resp.status_code == 422, f"第 {i} 次应 422"
        assert resp.get_json()["code"] == "PASSWORD_INVALID"

    fifth = client.put(f"{API}/auth/password", headers=header, json=payload)
    assert fifth.status_code == 429
    assert fifth.get_json()["code"] == "SESSION_VERIFY_ABORTED"

    # 不锁定账号、不计入登录失败计数
    assert login(client, username, DEFAULT_PASSWORD).status_code == 200


# ════════════════════════════════════════════════════════════════════
# B12 —— 客户端不得提交 user_id
# ════════════════════════════════════════════════════════════════════
def test_b12_client_supplied_user_id_rejected(client, new_account):
    """B-12 请求中出现 ``user_id`` → 400 ``INVALID_PARAM``（Body 与 query 均拒）。"""
    username, password, tokens = new_account
    header = auth_header(tokens["access_token"])

    cases = (
        (f"{API}/auth/login",
         {"json": {"username": username, "password": password, "user_id": 1}}),
        (f"{API}/auth/register",
         {"json": {"username": unique_username(), "password": DEFAULT_PASSWORD,
                   "agreement_version": "v1.0", "agreement_accepted": True, "user_id": 999}}),
        (f"{API}/auth/refresh",
         {"json": {"refresh_token": tokens["refresh_token"], "user_id": 1}}),
    )
    for url, kwargs in cases:
        resp = client.post(url, **kwargs)
        assert resp.status_code == 400, f"{url} 未拒绝 user_id"
        assert resp.get_json()["code"] == "INVALID_PARAM"

    resp = client.get(f"{API}/users/me?user_id=1", headers=header)
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"

    resp = client.put(f"{API}/auth/password", headers=header,
                      json={"old_password": password, "new_password": DEFAULT_PASSWORD2,
                            "confirm_password": DEFAULT_PASSWORD2, "user_id": 1})
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"
    # 该改密请求被拒后，会话仍然有效（未被误伤）
    assert client.get(f"{API}/users/me", headers=header).status_code == 200


# ════════════════════════════════════════════════════════════════════
# B13 —— 不泄露用户名存在性
# ════════════════════════════════════════════════════════════════════
def test_b13_no_username_enumeration_via_error(client, new_account):
    """B-13 失败响应**不区分**「账号不存在」与「密码错误」。"""
    username, _, _ = new_account
    existing = login(client, username, "wrongpw123")
    ghost = login(client, unique_username("ghost"), "wrongpw123")

    assert existing.status_code == ghost.status_code == 401
    assert existing.get_json()["code"] == ghost.get_json()["code"] == "CREDENTIALS_INVALID"
    assert existing.get_json()["message"] == ghost.get_json()["message"] == "用户名或密码错误"

    body = existing.get_json()
    assert sorted(body.keys()) == ["code", "data", "message", "request_id"]
    assert body["data"] is None
    assert username not in existing.get_data(as_text=True)


# ════════════════════════════════════════════════════════════════════
# 附加 —— 鉴权边界
# ════════════════════════════════════════════════════════════════════
def test_extra_requires_valid_bearer_token(client, new_account):
    """附加：缺 Token / 方案不对 / 被篡改 → 401 ``UNAUTHENTICATED``。"""
    _, _, tokens = new_account
    good = tokens["access_token"]
    tampered = good[:-3] + ("aaa" if not good.endswith("aaa") else "bbb")

    assert client.get(f"{API}/users/me").status_code == 401
    assert client.get(f"{API}/users/me", headers={"Authorization": "Token xyz"}).status_code == 401
    assert client.get(f"{API}/users/me", headers=auth_header(tampered)).status_code == 401
    assert client.post(f"{API}/auth/logout").status_code == 401
    assert client.put(f"{API}/auth/password", json={
        "old_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD2,
        "confirm_password": DEFAULT_PASSWORD2}).status_code == 401
    # 401 一律 UNAUTHENTICATED（不区分具体原因）
    assert client.get(f"{API}/users/me").get_json()["code"] == "UNAUTHENTICATED"


def test_extra_access_token_id_persisted_not_plaintext_refresh(client, new_account):
    """附加：DB 只存 refresh 的 SHA-256（64 hex），**不存明文**。"""
    import hashlib

    from tests.conftest import account_row as _acc
    from tests.conftest import session_rows

    username, _, tokens = new_account
    user_id = _acc(username)["id"]
    rows = session_rows(user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["refresh_token_hash"] == hashlib.sha256(
        tokens["refresh_token"].encode("utf-8")
    ).hexdigest()
    assert tokens["refresh_token"] != row["refresh_token_hash"]
    assert len(row["refresh_token_hash"]) == 64
    # jti 已落库（Session 权威：校验 jti 是否失效）
    assert row["access_token_id"] and len(row["access_token_id"]) == 32
