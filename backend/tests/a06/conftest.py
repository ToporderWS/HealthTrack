# -*- coding: utf-8 -*-
"""B4-PRE-01 · A-06 邮箱绑定态只读字段 —— pytest 装置（**独立目录**，不动既有计数单元）。

为什么另建 ``tests/a06/``
------------------------
与 ``tests/b3/`` 同一先例：本批新增用例必须可与既有基线**分离计数**
（B2＝47 / B3＝48 / pwreset＝153 / testsafety＝67 / batch3~8 / medical 全部保持不变）。

复用已 SEALED 的 TEST-INFRA 四重保护（**本装置不重复实现任何一层**）
------------------------------------------------------------------
- **D0**：根 ``conftest.py`` 已把 ``MYSQL_DB`` 钉死为 ``kangji_healthtrack_test``
  （fail-closed；pytest 内**无法**落到开发库）；
- **B 本批独占前缀**：账号一律 ``tsta6`` ＋ 6 位 hex（``tsta6`` ⊂ ``tst%``，仍受祖先守卫识别）；
- **C 本次创建集合**：清理按「前缀 ＋ 模块启动时 id 水位线」双条件，**只回收本模块造的行**；
- **A denylist**：``testsafety`` 引擎级咽喉点保护 ``top001`` 等 4 个保护账号。

本装置只触库 6 张与「邮箱绑定态」相关的表：``user_account`` / ``user_profile`` /
``user_session`` / ``login_failure_state`` / ``verification_code`` / ``password_reset_token``
（**不造任何业务数据**：records / tags / goals / export / 头像）。
"""
from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.password_reset import PURPOSE_EMAIL_BIND, normalize_email
from app.models import ALL_TABLES
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode
from app.services import mail_service

#: 与全仓统一：测试账号前缀（``tst``）；本批再叠独占 tag ``a6``
TEST_PREFIX = "tst"
BATCH_TAG = "a6"

#: 清理范围 = V1.0 全部 10 张业务表（不含 ``alembic_version``）
GUARDED_TABLES = tuple(ALL_TABLES)

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"

#: **测试专用 pepper**（伪造值；绝非任何环境的真实密钥，不出现在任何配置文件里）
TEST_PEPPER = "a06-test-only-pepper-DO-NOT-USE-IN-PROD"


# ══════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════
def unique_username(tag: str = BATCH_TAG) -> str:
    """唯一测试用户名（``tst`` + tag + 6 hex，≤ 20 位且字母开头）。"""
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def unique_email(prefix: str = BATCH_TAG) -> str:
    """唯一测试邮箱（``a6`` + 8 hex + ``@example.com``，示例域不真实投递）。"""
    return f"{prefix}{secrets.token_hex(4)}@example.com"


def counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def max_ids() -> Dict[str, int]:
    """全部受管表当前 ``MAX(id)`` 水位线（每个用例开始时取值）。"""
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COALESCE(MAX(id),0) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def purge_a06_rows(baseline_max: Dict[str, int]) -> None:
    """回收**本模块**写入的行（前缀 ＋ id 水位线双条件；不越界清别的模块）。

    条件形态与 ``tests/b3/conftest.py`` / ``tests/b2/conftest.py`` 一致：每条 DELETE
    都带 ``id`` 水位线或显式 id 集合 ⇒ ``testsafety`` 引擎级守卫可逐行证明「本次新建」。
    """
    factory = get_session_factory()
    with factory() as db:
        ids = [
            int(r[0])
            for r in db.execute(
                select(UserAccount.id).where(
                    UserAccount.username.like(f"{TEST_PREFIX}%"),
                    UserAccount.id > baseline_max["user_account"],
                )
            ).all()
        ]
        if ids:
            db.execute(delete(VerificationCode).where(VerificationCode.user_id.in_(ids)))
            db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id.in_(ids)))
            db.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
            db.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))
            db.execute(delete(UserAccount).where(UserAccount.id.in_(ids)))
        db.execute(
            delete(LoginFailureState).where(
                LoginFailureState.username.like(f"{TEST_PREFIX}%"),
                LoginFailureState.id > baseline_max["login_failure_state"],
            )
        )
        # 两张安全表：按 id 水位线清「本模块新增」＋「A-07 删号后可能留下的孤儿行」
        db.execute(
            delete(VerificationCode).where(VerificationCode.id > baseline_max["verification_code"])
        )
        db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.id > baseline_max["password_reset_token"]
            )
        )
        db.commit()


# ══════════════════════════════════════════════════════════════════
# HTTP 助手 —— 注册 / 登录 / A-06
# ══════════════════════════════════════════════════════════════════
def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_account(
    client, *, username: Optional[str] = None, password: str = DEFAULT_PASSWORD
) -> Tuple[str, int]:
    """通过真实 A-01 契约注册（``auto_login=True``）；返回 ``(username, user_id)``。"""
    username = username or unique_username()
    resp = client.post(
        f"{API}/auth/register",
        json={
            "username": username,
            "password": password,
            "agreement_version": "v1.0",
            "agreement_accepted": True,
            "auto_login": True,
        },
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    uid = int(resp.get_json()["data"]["user"]["user_id"])
    return username, uid


def access_token_of(client, username: str, password: str = DEFAULT_PASSWORD) -> str:
    """通过 A-02 登录取 Access Token。"""
    resp = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return str(resp.get_json()["data"]["tokens"]["access_token"])


def register_token(
    client, *, username: Optional[str] = None, password: str = DEFAULT_PASSWORD
) -> Tuple[str, int, str]:
    """注册 ＋ 登录，返回 ``(username, user_id, access_token)``。"""
    username, uid = register_account(client, username=username, password=password)
    return username, uid, access_token_of(client, username, password)


def get_me(client, token: str):
    """A-06 ``GET /users/me``。"""
    return client.get(f"{API}/users/me", headers=auth_header(token))


# ══════════════════════════════════════════════════════════════════
# HTTP 助手 —— PR-04 / PR-05 邮箱绑定（**只为构造「已验证绑定」态**）
# ══════════════════════════════════════════════════════════════════
def req_bind(client, token: str, email: Any, password: Any = DEFAULT_PASSWORD):
    """PR-04 发起邮箱绑定。"""
    return client.post(
        f"{API}/auth/email/bind-request",
        headers=auth_header(token),
        json={"email": email, "current_password": password},
    )


def req_confirm_bind(client, token: str, email: Any, code: Any, password: Any = DEFAULT_PASSWORD):
    """PR-05 校验绑定验证码。"""
    return client.post(
        f"{API}/auth/email/bind-confirm",
        headers=auth_header(token),
        json={"email": email, "code": code, "current_password": password},
    )


def latest_bind_code_for(email: str) -> Optional[str]:
    """从**内存投递箱**取发给该邮箱的最新一封 **email_bind** 邮件里的验证码。

    ⚠️ 只在 ``MAIL_BACKEND=memory`` 下可用 —— 读的是**投递载荷**（邮件的等价物），
    **不是**日志、**也不是** DB 明文（DB 里只有 ``code_hash``）。
    """
    target = normalize_email(email)
    for item in reversed(mail_service.memory_outbox()):
        if item.get("purpose") != PURPOSE_EMAIL_BIND:
            continue
        if normalize_email(item.get("to")) == target:
            return str(item.get("code"))
    return None


def bind_email_via_api(
    client, token: str, email: str, password: str = DEFAULT_PASSWORD
) -> str:
    """走**真实契约**完成一次邮箱绑定；返回本次验证码（供断言）。

    本批只用它构造「已验证绑定」这一**前置状态**；PR-04 / PR-05 自身的判据
    由 ``tests/b3/`` 独立封板覆盖，本批**不改也不重复**。
    """
    r = req_bind(client, token, email, password)
    assert r.status_code == 200, r.get_data(as_text=True)
    code = latest_bind_code_for(email)
    assert code is not None, "PR-04 未投递 email_bind 验证码"
    c = req_confirm_bind(client, token, email, code, password)
    assert c.status_code == 200, c.get_data(as_text=True)
    return code


# ══════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _a06_mail_env(app):  # noqa: ANN001
    """注入**测试专用** pepper ＋ 强制内存邮件后端（不依赖启动环境变量；结束时还原）。"""
    prev_pepper = app.config.get("PASSWORD_RESET_PEPPER")
    prev_backend = app.config.get("MAIL_BACKEND")
    app.config["PASSWORD_RESET_PEPPER"] = TEST_PEPPER
    app.config["MAIL_BACKEND"] = "memory"
    yield
    app.config["PASSWORD_RESET_PEPPER"] = prev_pepper
    app.config["MAIL_BACKEND"] = prev_backend


@pytest.fixture(autouse=True)
def _clear_mailbox(app):  # noqa: ANN001
    """每次用例前后清空内存投递箱，避免跨用例串味。"""
    mail_service.drain_memory_outbox()
    yield
    mail_service.drain_memory_outbox()


@pytest.fixture(autouse=True)
def _a06_scope_guard(app):  # noqa: ANN001
    """用例级测试数据守卫：运行前后对 10 张表取快照，结束清理并断言逐表还原。

    依赖祖先 ``app`` fixture（会话级）以确保引擎已初始化。
    """
    before = counts()
    baseline_max = max_ids()
    yield
    purge_a06_rows(baseline_max)
    after = counts()
    assert after == before, f"A-06 测试数据未完全清理：before={before} after={after}"


__all__: List[str] = [
    "API",
    "DEFAULT_PASSWORD",
    "TEST_PEPPER",
    "auth_header",
    "bind_email_via_api",
    "get_me",
    "register_account",
    "register_token",
    "unique_email",
    "unique_username",
]
