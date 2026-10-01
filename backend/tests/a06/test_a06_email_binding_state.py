# -*- coding: utf-8 -*-
"""B4-PRE-01 · A-06 邮箱绑定态只读字段（``GET /api/v1/users/me`` **add-only** 扩展）。

本批**只做一件事**：让前端能**读取当前已经存在**的绑定结果。
不改 PR-01~PR-05、不改 DB 结构、不改 testsafety、不改前端、不重设计绑定机制。

| # | 用例 |
|---|---|
| 1 | ``mask_email`` 掩码规则（确定性 / 短 local 不越界 / 不含完整邮箱 / 非法输入为 ``None``） |
| 2 | email=NULL ⇒ ``email_bound=false`` / ``email_masked=null``（单元） |
| 3 | email 有值但 ``email_verified_at=NULL`` ⇒ ``false`` / ``null``（单元；DB CHECK 下不可达态） |
| 4 | email ＋ ``email_verified_at`` 均有值 ⇒ ``true`` / 安全掩码（单元） |
| 5 | 任何路径都不返回完整 ``email`` / ``email_verified_at``（单元，逐字扫描） |
| 6 | 原有 4 字段（``user_id`` / ``username`` / ``created_at`` / ``profile_initialized``）零漂移 |
| 7 | 响应恰为「原 4 ＋ 新 2」六键（HTTP，add-only） |
| 8 | 未绑定账号 HTTP ⇒ ``false`` / ``null`` |
| 9 | 走**真实 PR-04→PR-05** 绑定后 HTTP ⇒ ``true`` / 掩码；原始报文不含完整邮箱 |
| 10 | 未绑定账号仍可**登录 / 改密 / 注销**（不得强制绑定邮箱） |
| 11 | 响应不含 ``password_hash`` / ``password_algo`` / ``role`` / ``tokens`` |
| 12 | 无 Token ⇒ ``401 UNAUTHENTICATED``（回归） |

> 掩码是**服务端**生成：前端拿不到完整邮箱、也无从自行掩码（需求方 §二）。
"""
from __future__ import annotations

import json
from datetime import datetime

from app.core.db import get_session_factory
from app.services import auth_service

from tests.a06.conftest import (
    API,
    DEFAULT_PASSWORD,
    auth_header,
    bind_email_via_api,
    get_me,
    register_token,
    unique_email,
)

#: 被测符号（**测试先行**：``mask_email`` 在旧代码上不存在 ⇒ 逐条 RED，而非整个模块收集失败）
mask_email = getattr(auth_service, "mask_email", None)


def _mask(raw):
    """取掩码实现的**唯一入口**（未实现时给出明确 RED 断言，而非 AttributeError）。"""
    assert mask_email is not None, "auth_service.mask_email 尚未实现（测试先行 RED）"
    return mask_email(raw)

NEW_PASSWORD = "newpass9876"

#: 单元测试用的**最小身份桩**（`build_current_user` 只读这 5 个字段；``id=0`` 无档案）
STUB_CREATED_AT = datetime(2026, 9, 13, 10, 20, 30)


class _StubAccount:
    def __init__(self, email=None, verified_at=None, uid=0, username="tsta6stub"):
        self.id = uid
        self.username = username
        self.created_at = STUB_CREATED_AT
        self.email = email
        self.email_verified_at = verified_at


def _build(app, account):  # noqa: ANN001
    """在真实（只读 SELECT）会话里调用 ``build_current_user``。"""
    factory = get_session_factory()
    with factory() as db:
        return auth_service.build_current_user(db, account)


# ══════════════════════════════════════════════════════════════════
# 1. mask_email 掩码规则
# ══════════════════════════════════════════════════════════════════
_MASK_CASES = [
    ("alice@example.com", "a***@example.com"),
    ("a@b.com", "a***@b.com"),          # 极短 local-part：不越界、不退化为完整邮箱
    ("zhangsan@qq.com", "z***@qq.com"),
    ("a6deadbeef@example.com", "a***@example.com"),
]


def test_mask_email_is_deterministic_and_masks_local_part():
    for raw, expected in _MASK_CASES:
        out = _mask(raw)
        assert out == expected, (raw, out, expected)
        assert _mask(raw) == out, "掩码必须确定性"
        assert out != raw, "掩码不得等于完整邮箱"
        assert raw not in out, "掩码不得包含完整邮箱"


def test_mask_email_never_out_of_range_for_short_local():
    """短 local-part 不得越界（``local[:1]`` 对长度 1 安全）。"""
    for raw in ("a@x.io", "1@x.io", "_@x.io"):
        out = _mask(raw)
        assert isinstance(out, str) and out.endswith("@x.io"), (raw, out)


def test_mask_email_rejects_null_empty_and_malformed():
    for raw in (None, "", "   ", "no-at-sign", "@x.com", "a@", "a@@b"):
        assert _mask(raw) is None, raw


def test_mask_email_keeps_domain_for_recognition():
    """掩码必须保留域名（供用户识别），但 local-part 必被遮盖。"""
    out = _mask("someone@qq.com")
    assert out is not None and out.endswith("@qq.com")
    assert "someone" not in out


# ══════════════════════════════════════════════════════════════════
# 2~6. build_current_user 三态 + 无泄露 + 原 4 字段零漂移（单元）
# ══════════════════════════════════════════════════════════════════
def test_email_null_means_not_bound(app):  # noqa: ANN001
    data = _build(app, _StubAccount(email=None, verified_at=None))
    assert data["email_bound"] is False
    assert data["email_masked"] is None


def test_email_nonnull_but_unverified_means_not_bound(app):  # noqa: ANN001
    """DB ``ck_user_account_email_pair`` 下不可达态 —— 实现**不得**只看 ``email`` 非空。"""
    data = _build(app, _StubAccount(email="a6ghost@example.com", verified_at=None))
    assert data["email_bound"] is False
    assert data["email_masked"] is None


def test_email_and_verified_means_bound_with_mask(app):  # noqa: ANN001
    data = _build(
        app,
        _StubAccount(email="a6alice@example.com", verified_at=STUB_CREATED_AT),
    )
    assert data["email_bound"] is True
    assert data["email_masked"] == "a***@example.com"
    assert data["email_masked"] != "a6alice@example.com"


def test_build_current_user_never_leaks_email_or_verified_at(app):  # noqa: ANN001
    """三种状态下：响应键集合固定，且**任何字段都不含**完整邮箱 / 验证时间。"""
    expected_keys = {
        "user_id", "username", "created_at", "profile_initialized",
        "email_bound", "email_masked",
    }
    email = "a6leak@example.com"
    cases = (
        _StubAccount(email=None, verified_at=None),
        _StubAccount(email=email, verified_at=None),
        _StubAccount(email=email, verified_at=STUB_CREATED_AT),
    )
    for account in cases:
        data = _build(app, account)
        assert set(data.keys()) == expected_keys, sorted(data.keys())
        blob = json.dumps(data, ensure_ascii=False)
        assert email not in blob, "响应不得出现完整邮箱"
        assert "email_verified_at" not in blob, "响应不得出现 email_verified_at"


def test_original_four_fields_semantics_unchanged(app):  # noqa: ANN001
    """原有 4 字段：字段名 / 类型 / 语义逐字保持。"""
    data = _build(app, _StubAccount(email=None, verified_at=None))
    assert data["user_id"] == 0
    assert isinstance(data["user_id"], int)
    assert data["username"] == "tsta6stub"
    assert data["created_at"] == "2026-09-13 10:20:30"
    assert data["profile_initialized"] is False


# ══════════════════════════════════════════════════════════════════
# 7~9. HTTP 契约（add-only）
# ══════════════════════════════════════════════════════════════════
def test_a06_response_keys_are_add_only(client):
    _username, _uid, token = register_token(client)
    resp = get_me(client, token)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()["data"]
    assert sorted(data.keys()) == [
        "created_at", "email_bound", "email_masked",
        "profile_initialized", "user_id", "username",
    ], sorted(data.keys())


def test_a06_unbound_account_reports_false_and_null(client):
    _username, _uid, token = register_token(client)
    resp = get_me(client, token)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["email_bound"] is False
    assert data["email_masked"] is None


def test_a06_bound_account_reports_true_and_mask(client):
    """走**真实契约**（PR-04 → PR-05）绑定，再读 A-06。"""
    _username, _uid, token = register_token(client)
    email = unique_email()
    bind_email_via_api(client, token, email)

    resp = get_me(client, token)
    assert resp.status_code == 200
    raw = resp.get_data(as_text=True)
    data = resp.get_json()["data"]

    assert data["email_bound"] is True
    assert data["email_masked"] == _mask(email)
    assert data["email_masked"] != email
    # ★ 原始报文逐字扫描：不得出现完整邮箱 / 验证时间
    assert email not in raw, "A-06 响应泄漏完整邮箱"
    assert "email_verified_at" not in raw
    # 掩码保留域名（供识别）
    assert data["email_masked"].endswith("@" + email.split("@", 1)[1])


# ══════════════════════════════════════════════════════════════════
# 10~12. 兼容性与回归
# ══════════════════════════════════════════════════════════════════
def test_unbound_account_can_still_login_change_password_and_close(client):
    """未绑定邮箱的账号**不得**被强制绑定：登录 / 改密 / 注销全部照常。"""
    username, _uid, token = register_token(client)

    # ① 未绑定仍然是「持续可用」状态
    assert get_me(client, token).get_json()["data"]["email_bound"] is False

    # ② 登录
    assert client.post(
        f"{API}/auth/login", json={"username": username, "password": DEFAULT_PASSWORD}
    ).status_code == 200

    # ③ 改密
    changed = client.put(
        f"{API}/auth/password",
        headers=auth_header(token),
        json={
            "old_password": DEFAULT_PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert changed.status_code == 200, changed.get_data(as_text=True)

    # ④ 用新密码登录后注销
    relogin = client.post(
        f"{API}/auth/login", json={"username": username, "password": NEW_PASSWORD}
    )
    assert relogin.status_code == 200
    new_token = relogin.get_json()["data"]["tokens"]["access_token"]
    closed = client.delete(
        f"{API}/users/me",
        headers=auth_header(new_token),
        json={"password": NEW_PASSWORD, "confirm_text": "注销账号"},
    )
    assert closed.status_code == 200, closed.get_data(as_text=True)
    assert closed.get_json()["data"]["account_closed"] is True


def test_a06_never_exposes_other_sensitive_fields(client):
    _username, _uid, token = register_token(client)
    data = get_me(client, token).get_json()["data"]
    for forbidden in (
        "password_hash", "password_algo", "role", "tokens",
        "email", "email_verified_at", "user_profile", "profile",
    ):
        assert forbidden not in data, forbidden


def test_a06_without_token_is_401(client):
    assert client.get(f"{API}/users/me").status_code == 401
