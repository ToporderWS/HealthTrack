# -*- coding: utf-8 -*-
"""B2 找回密码 API —— pytest 装置（**独立目录**，不动 ``tests/pwreset`` 的 153 项基线）。

为什么另建 ``tests/b2/``
-----------------------
需求方 §十三 把「B2 新增专测」与「``tests/pwreset``」列为**两个独立步骤**
⇒ B2 的用例必须可与 B1 基线分离计数（``pytest tests/b2`` vs ``pytest tests/pwreset``）。

复用 B1-R-FIX 封板的四重保护
---------------------------
- **D0**：根 ``conftest.py`` 已把 ``MYSQL_DB`` 钉死为 ``kangji_healthtrack_test``
  （fail-closed；pytest 内**无法**落到开发库）；
- **B 本批独占前缀**：账号一律 ``tstb2`` + 6 位 hex（``tstb2`` ⊂ ``tst%``，仍受祖先守卫识别）；
- **C 本次创建集合**：清理按「前缀 ＋ 模块启动时 id 水位线」双条件，**只回收本模块造的行**；
- **A denylist**：``testsafety`` 引擎级咽喉点保护 ``top001`` 等 4 个保护账号
  （本装置**不重复实现**，由守卫统一承担）。

不触库的东西一律不碰：本模块只用 ``user_account`` / ``user_session`` /
``verification_code`` / ``password_reset_token``（**不造业务数据**）。
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.password_reset import normalize_email
from app.core.security import now_local
from app.models import ALL_TABLES
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode
from app.services import mail_service

#: 与全仓统一：测试账号前缀（``tst``）；本批再叠独占 tag ``b2``
TEST_PREFIX = "tst"
BATCH_TAG = "b2"

#: 清理范围 = V1.0 全部 10 张业务表（不含 ``alembic_version``）
GUARDED_TABLES = tuple(ALL_TABLES)

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"
NEW_PASSWORD = "newpass9876"

#: **测试专用 pepper**（伪造值；绝非任何环境的真实密钥，不出现在任何配置文件里）
TEST_PEPPER = "b2-test-only-pepper-DO-NOT-USE-IN-PROD"


# ══════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════
def unique_username(tag: str = BATCH_TAG) -> str:
    """唯一测试用户名（``tst`` + tag + 6 hex，≤ 20 位且字母开头）。"""
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def max_ids() -> Dict[str, int]:
    """全部受管表当前 ``MAX(id)`` 水位线（模块开始时取值）。"""
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COALESCE(MAX(id),0) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def purge_b2_rows(baseline_max: Dict[str, int]) -> None:
    """回收**本模块**写入的行（前缀 ＋ id 水位线双条件；不越界清别的模块）。"""
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
        # 两张新表：按 id 水位线清「本模块新增」＋「A-07 删号后可能留下的孤儿行」
        db.execute(
            delete(VerificationCode).where(VerificationCode.id > baseline_max["verification_code"])
        )
        db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.id > baseline_max["password_reset_token"]
            )
        )
        db.commit()


def bind_verified_email(user_id: int, email: str) -> None:
    """把「已验证邮箱」绑到账号上（**唯一合法写入路径的等价物**）。

    ⚠️ ``user_account.email`` 只存**已验证**邮箱（``ck_user_account_email_pair``
    强制 ``email`` 与 ``email_verified_at`` 同时非空）⇒ 本助手同时写两列。
    """
    factory = get_session_factory()
    with factory() as db:
        acc = db.get(UserAccount, int(user_id))
        assert acc is not None, "账号不存在，无法绑定邮箱"
        acc.email = normalize_email(email)
        acc.email_verified_at = now_local()
        db.commit()


def account_id_of(username: str) -> Optional[int]:
    factory = get_session_factory()
    with factory() as db:
        return db.execute(
            select(UserAccount.id).where(UserAccount.username == username)
        ).scalar()


def one(sql: str, **params):
    factory = get_session_factory()
    with factory() as db:
        return db.execute(text(sql), params).scalar()


def rows(sql: str, **params):
    factory = get_session_factory()
    with factory() as db:
        return db.execute(text(sql), params).all()


def exec_sql(sql: str, **params) -> None:
    """测试专用：构造特殊状态（过期 / 冷却已过 / 已消费 / 越权 purpose）。"""
    factory = get_session_factory()
    with factory() as db:
        db.execute(text(sql), params)
        db.commit()


# ══════════════════════════════════════════════════════════════════
# HTTP 助手
# ══════════════════════════════════════════════════════════════════
def register_account(
    client, *, username: Optional[str] = None, password: str = DEFAULT_PASSWORD
) -> Tuple[str, int]:
    """通过真实 A-01 契约注册；返回 ``(username, user_id)``。"""
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


def register_with_email(client, *, email: Optional[str] = None) -> Tuple[str, int, str]:
    """注册 + 绑定已验证邮箱；返回 ``(username, user_id, email)``。"""
    username, uid = register_account(client)
    email = normalize_email(email or f"{username}@example.com")
    bind_verified_email(uid, email)
    return username, uid, email


def access_token_of(client, username: str, password: str = DEFAULT_PASSWORD) -> str:
    """通过 A-02 登录取 Access Token（用于需登录的 A-05 / A-07 用例）。"""
    resp = client.post(
        f"{API}/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return str(resp.get_json()["data"]["tokens"]["access_token"])


def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def req_reset(client, username: str):
    return client.post(f"{API}/auth/password-reset/request", json={"username": username})


def req_verify(client, username: str, code: str):
    return client.post(
        f"{API}/auth/password-reset/verify", json={"username": username, "code": code}
    )


def req_confirm(client, token: str, new_password: str = NEW_PASSWORD, confirm: Optional[str] = None):
    return client.post(
        f"{API}/auth/password-reset/confirm",
        json={
            "reset_token": token,
            "new_password": new_password,
            "confirm_password": new_password if confirm is None else confirm,
        },
    )


def latest_code_for(email: str) -> Optional[str]:
    """从**内存投递箱**取发给该邮箱的最新一封邮件的验证码（测试专用读取路径）。

    ⚠️ 这只在 ``MAIL_BACKEND=memory`` 下可用 —— 它读的是**投递载荷**（邮件的等价物），
    **不是**日志、**也不是** DB 明文（DB 里只有 ``code_hash``）。
    """
    target = normalize_email(email)
    for item in reversed(mail_service.memory_outbox()):
        if normalize_email(item.get("to")) == target:
            return str(item.get("code"))
    return None


def mailbox_codes() -> list:
    return [str(i.get("code")) for i in mail_service.memory_outbox()]


# ══════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _test_pepper(app):  # noqa: ANN001
    """注入**测试专用** pepper（不依赖启动环境变量；结束时还原）。"""
    prev = app.config.get("PASSWORD_RESET_PEPPER")
    app.config["PASSWORD_RESET_PEPPER"] = TEST_PEPPER
    yield
    app.config["PASSWORD_RESET_PEPPER"] = prev


@pytest.fixture(autouse=True)
def _clear_mailbox(app):  # noqa: ANN001
    """每次用例前后清空内存投递箱，避免跨用例串味。"""
    mail_service.drain_memory_outbox()
    yield
    mail_service.drain_memory_outbox()


@pytest.fixture(autouse=True)
def _b2_scope_guard(app):  # noqa: ANN001
    """模块级测试数据守卫：运行前后对 10 张表取快照，结束清理并断言逐表还原。

    依赖祖先 ``app`` fixture（会话级）以确保引擎已初始化。
    """
    before = counts()
    baseline_max = max_ids()
    yield
    purge_b2_rows(baseline_max)
    after = counts()
    assert after == before, f"B2 测试数据未完全清理：before={before} after={after}"
