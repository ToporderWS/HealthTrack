# -*- coding: utf-8 -*-
"""B3 邮箱绑定 API —— pytest 装置（**独立目录**，不动 ``tests/b2``＝47 / ``tests/pwreset``＝153）。

为什么另建 ``tests/b3/``
-----------------------
需求方 B3 授权 §八 把「B3 新增专测」与既有 ``tests/b2`` / ``tests/pwreset`` 列为
**相互独立**的计数单元 ⇒ B3 用例必须可与既有基线分离计数。

复用 B1-R-FIX 封板的四重保护（**本装置不重复实现任何一层**）
-----------------------------------------------------------
- **D0**：根 ``conftest.py`` 已把 ``MYSQL_DB`` 钉死为 ``kangji_healthtrack_test``
  （fail-closed；pytest 内**无法**落到开发库）；
- **B 本批独占前缀**：账号一律 ``tstb3`` + 6 位 hex（``tstb3`` ⊂ ``tst%``，仍受祖先守卫识别）；
- **C 本次创建集合**：清理按「前缀 ＋ 模块启动时 id 水位线」双条件，**只回收本模块造的行**；
- **A denylist**：``testsafety`` 引擎级咽喉点保护 ``top001`` 等 4 个保护账号。

不触库的东西一律不碰：本模块只用 ``user_account`` / ``user_profile`` / ``user_session`` /
``verification_code`` / ``password_reset_token`` / ``login_failure_state``
（**不造任何业务数据**：records / tags / goals / export / 头像）。
"""
from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.password_reset import (
    PURPOSE_EMAIL_BIND,
    PURPOSE_PASSWORD_RESET,
    normalize_email,
)
from app.core.security import now_local
from app.models import ALL_TABLES
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode
from app.services import mail_service

#: 与全仓统一：测试账号前缀（``tst``）；本批再叠独占 tag ``b3``
TEST_PREFIX = "tst"
BATCH_TAG = "b3"

#: 清理范围 = V1.0 全部 10 张业务表（不含 ``alembic_version``）
GUARDED_TABLES = tuple(ALL_TABLES)

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"
NEW_PASSWORD = "newpass9876"

#: **测试专用 pepper**（伪造值；绝非任何环境的真实密钥，不出现在任何配置文件里）
TEST_PEPPER = "b3-test-only-pepper-DO-NOT-USE-IN-PROD"


# ══════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════
def unique_username(tag: str = BATCH_TAG) -> str:
    """唯一测试用户名（``tst`` + tag + 6 hex，≤ 20 位且字母开头）。"""
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def unique_email(prefix: str = "b3") -> str:
    """唯一测试邮箱（``b3`` + 8 hex + ``@example.com``，示例域不真实投递）。"""
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


def purge_b3_rows(baseline_max: Dict[str, int]) -> None:
    """回收**本模块**写入的行（前缀 ＋ id 水位线双条件；不越界清别的模块）。

    条件形态与 ``tests/b2/conftest.py`` 一致：每条 DELETE 都带 ``id`` 水位线
    或显式 id 集合 ⇒ ``testsafety`` 引擎级守卫可逐行证明「本次新建」。
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


def one(sql: str, **params):
    factory = get_session_factory()
    with factory() as db:
        return db.execute(text(sql), params).scalar()


def rows(sql: str, **params) -> List[Any]:
    factory = get_session_factory()
    with factory() as db:
        return db.execute(text(sql), params).all()


def exec_sql(sql: str, **params) -> None:
    """测试专用：构造特殊状态（过期 / 冷却已过 / 已消费 / 越权 purpose）。"""
    factory = get_session_factory()
    with factory() as db:
        db.execute(text(sql), params)
        db.commit()


def account_id_of(username: str) -> Optional[int]:
    factory = get_session_factory()
    with factory() as db:
        return db.execute(
            select(UserAccount.id).where(UserAccount.username == username)
        ).scalar()


def failure_state_of(username: str) -> Optional[Dict[str, Any]]:
    """读取登录失败状态行（``dict`` 或 ``None``）。"""
    factory = get_session_factory()
    with factory() as db:
        row = db.execute(
            select(LoginFailureState).where(LoginFailureState.username == username.lower())
        ).scalars().first()
        if row is None:
            return None
        return {
            "fail_count": int(row.fail_count),
            "lock_level": int(row.lock_level),
            "locked_until": row.locked_until,
            "first_fail_at": row.first_fail_at,
        }


# ══════════════════════════════════════════════════════════════════
# HTTP 助手 —— 注册 / 登录
# ══════════════════════════════════════════════════════════════════
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


def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client, username: str, password: str = DEFAULT_PASSWORD):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


# ══════════════════════════════════════════════════════════════════
# HTTP 助手 —— PR-04 / PR-05 邮箱绑定
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
    """走**真实契约**完成一次邮箱绑定；返回本次验证码（供断言）。"""
    r = req_bind(client, token, email, password)
    assert r.status_code == 200, r.get_data(as_text=True)
    code = latest_bind_code_for(email)
    assert code is not None, "PR-04 未投递 email_bind 验证码"
    c = req_confirm_bind(client, token, email, code, password)
    assert c.status_code == 200, c.get_data(as_text=True)
    return code


def rewind_bind_code_cooldown(uid: int, seconds: int = 120) -> None:
    """把 ``email_bind`` 验证码的 ``created_at`` 回拨，以解除 60 秒服务端重发冷却。

    **仅测试装置技巧**，不改变产品语义；冷却行为本身由
    ``test_pr04_bind_request.py`` 独立覆盖。
    """
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL :s SECOND) "
        "WHERE user_id=:u AND purpose='email_bind'",
        s=seconds,
        u=uid,
    )


# ══════════════════════════════════════════════════════════════════
# HTTP 助手 —— PR-01 / PR-02 / PR-03 找回密码（回归与被隔离对象）
# ══════════════════════════════════════════════════════════════════
def req_reset(client, username: str):
    return client.post(f"{API}/auth/password-reset/request", json={"username": username})


def req_verify(client, username: str, code: Any):
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


def latest_reset_code_for(email: str) -> Optional[str]:
    """取发给该邮箱的最新一封 **password_reset** 邮件验证码。"""
    target = normalize_email(email)
    for item in reversed(mail_service.memory_outbox()):
        if item.get("purpose") != PURPOSE_PASSWORD_RESET:
            continue
        if normalize_email(item.get("to")) == target:
            return str(item.get("code"))
    return None


def mailbox_by_purpose(purpose: str) -> List[Dict[str, Any]]:
    return [i for i in mail_service.memory_outbox() if i.get("purpose") == purpose]


def obtain_reset_token(client, username: str, email: str) -> str:
    """完整走 PR-01 + PR-02，取得一次性 ``reset_token``（绕过冷却）。"""
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id = (SELECT id FROM user_account WHERE username = :u)",
        u=username,
    )
    req_reset(client, username)
    code = latest_reset_code_for(email)
    assert code is not None, "PR-01 未投递 password_reset 验证码（账号邮箱是否已验证？）"
    resp = req_verify(client, username, code)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return str(resp.get_json()["data"]["reset_token"])


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
def _b3_scope_guard(app):  # noqa: ANN001
    """用例级测试数据守卫：运行前后对 10 张表取快照，结束清理并断言逐表还原。

    依赖祖先 ``app`` fixture（会话级）以确保引擎已初始化。
    """
    before = counts()
    baseline_max = max_ids()
    yield
    purge_b3_rows(baseline_max)
    after = counts()
    assert after == before, f"B3 测试数据未完全清理：before={before} after={after}"
