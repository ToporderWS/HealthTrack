# -*- coding: utf-8 -*-
"""A. 正向流程（6 项）—— 注册 → 登录 → 当前用户 → 刷新 → 登出 → 改密。"""
from __future__ import annotations

from tests.conftest import (
    API,
    DEFAULT_PASSWORD,
    DEFAULT_PASSWORD2,
    account_row,
    auth_header,
    login,
    register,
    tokens_of,
    unique_username,
)


def test_a1_register_success(client):
    """A-1 注册成功：201 + 用户对象 + Token 对 + 协议留痕。"""
    username, resp = register(client, unique_username())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "注册成功"
    data = body["data"]
    assert data["user"]["username"] == username
    assert isinstance(data["user"]["user_id"], int)
    assert data["user"]["created_at"]

    tokens = data["tokens"]
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token_expires_in"] == 7200          # 2 小时（冻结）
    assert tokens["refresh_token_expires_in"] == 2592000      # 30 天（冻结）

    # 协议同意：服务端留痕（F-008，不能只靠前端）
    row = account_row(username)
    assert row is not None and row["terms_agreed_at"] is not None
    assert row["agreement_version"] == "v1.0"
    assert row["role"] == "user"


def test_a1b_register_without_auto_login(client):
    """A-1 附加：``auto_login=false`` 时不签发 Token。"""
    _, resp = register(client, unique_username(), auto_login=False)
    assert resp.status_code == 201
    assert resp.get_json()["data"]["tokens"] is None


def test_a2_login_success(client, new_account):
    """A-2 登录成功：200 + 新建会话 + ``profile_initialized``。"""
    username, password, _ = new_account
    resp = login(client, username, password)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "登录成功"
    assert body["data"]["user"]["username"] == username
    assert body["data"]["profile_initialized"] is False
    tokens = body["data"]["tokens"]
    assert tokens["access_token"] and tokens["refresh_token"]
    # 用户名大小写不敏感（服务端统一小写）
    assert login(client, username.upper(), password).status_code == 200


def test_a3_get_me_success(client, new_account):
    """A-3 ``GET /users/me`` 成功：原 4 字段 ＋ B4-PRE-01 追加 ``email_bound`` / ``email_masked``。"""
    username, _, tokens = new_account
    resp = client.get(f"{API}/users/me", headers=auth_header(tokens["access_token"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["username"] == username
    assert sorted(data.keys()) == [
        "created_at", "email_bound", "email_masked",
        "profile_initialized", "user_id", "username",
    ]
    # 敏感字段绝不返回（B4-PRE-01：完整邮箱 / 验证时间同样绝不返回）
    for forbidden in ("password_hash", "password_algo", "role", "tokens",
                      "email", "email_verified_at"):
        assert forbidden not in data


def test_a4_refresh_success(client, new_account):
    """A-4 刷新成功：返回新的 Token 对，且新 refresh 可用。"""
    _, _, tokens = new_account
    resp = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "成功"
    new_tokens = body["data"]
    assert sorted(new_tokens.keys()) == [
        "access_token", "access_token_expires_in", "refresh_token",
        "refresh_token_expires_in", "token_type",
    ]
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # 新 access 可用
    assert client.get(
        f"{API}/users/me", headers=auth_header(new_tokens["access_token"])
    ).status_code == 200


def test_a5_logout_success(client, new_account):
    """A-5 登出成功：200 + 当前会话失效（不删除业务数据）。"""
    _, _, tokens = new_account
    header = auth_header(tokens["access_token"])
    resp = client.post(f"{API}/auth/logout", headers=header)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "已退出登录"
    assert body["data"] is None
    # 幂等口径：重复调用 → 401（会话已失效）
    assert client.post(f"{API}/auth/logout", headers=header).status_code == 401


def test_a6_change_password_success(client, new_account):
    """A-6 改密成功：200 + 全部会话失效 + 新密码可登录、旧密码不可登录。"""
    username, password, tokens = new_account
    resp = client.put(
        f"{API}/auth/password",
        headers=auth_header(tokens["access_token"]),
        json={
            "old_password": password,
            "new_password": DEFAULT_PASSWORD2,
            "confirm_password": DEFAULT_PASSWORD2,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "密码已修改，请重新登录"
    assert body["data"]["all_sessions_revoked"] is True

    assert login(client, username, password).status_code == 401        # 旧密码失效
    assert login(client, username, DEFAULT_PASSWORD2).status_code == 200  # 新密码可用
