# -*- coding: utf-8 -*-
"""S2 第二批 —— pytest 公共装置。

设计约束：
1. **不新建数据库、不新建表、不新建账号**：直接复用本机 `.env.development` 已配置的
   开发库 `kangji_healthtrack`（与 `scripts/verify_s2_batch1.py --db` 同一口径）。
2. **测试数据自清理**：所有测试用户名统一前缀 ``tst``；会话结束按前缀删除，
   并断言「运行前后行数一致」，**不污染开发库**。
3. **不回显任何密钥**：装置不打印口令 / Token 明文。
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest
from sqlalchemy import delete, select, text, update

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 复用本机已配置的开发连接（不覆盖 .env 中的库名/账号）
os.environ.setdefault("APP_ENV", "development")

from app import create_app  # noqa: E402
from app.core.db import get_engine, get_session_factory  # noqa: E402
from app.models.login_failure_state import LoginFailureState  # noqa: E402
from app.models.user_account import UserAccount  # noqa: E402
from app.models.user_profile import UserProfile  # noqa: E402
from app.models.user_session import UserSession  # noqa: E402

#: 测试用户名前缀（username 规则：4–20 位、字母开头，前缀+6 位 hex = 9 位）
TEST_PREFIX = "tst"
#: 本批涉及的表（自清理范围）
SCOPED_TABLES = ("user_account", "user_profile", "user_session", "login_failure_state")

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"
DEFAULT_PASSWORD2 = "xyz98765"


# ════════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════════
def unique_username(tag: str = "") -> str:
    """生成唯一测试用户名（统一前缀，便于自清理）。"""
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(
    client,
    username: Optional[str] = None,
    password: str = DEFAULT_PASSWORD,
    *,
    agreement_version: str = "v1.0",
    agreement_accepted: Any = True,
    auto_login: Optional[bool] = True,
    extra: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Any]:
    """调用 A-01；返回 ``(username, response)``。"""
    username = username or unique_username()
    body: Dict[str, Any] = {
        "username": username,
        "password": password,
        "agreement_version": agreement_version,
        "agreement_accepted": agreement_accepted,
    }
    if auto_login is not None:
        body["auto_login"] = auto_login
    if extra:
        body.update(extra)
    return username, client.post(f"{API}/auth/register", json=body)


def tokens_of(resp) -> Dict[str, Any]:
    return (resp.get_json() or {}).get("data", {}).get("tokens") or {}


def login(client, username: str, password: str = DEFAULT_PASSWORD):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def row_counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
            for t in SCOPED_TABLES
        }


def purge_test_rows() -> None:
    """按前缀清理测试数据（子表 → 主表顺序）。"""
    factory = get_session_factory()
    with factory() as db:
        ids = [
            int(r[0])
            for r in db.execute(
                select(UserAccount.id).where(UserAccount.username.like(f"{TEST_PREFIX}%"))
            ).all()
        ]
        if ids:
            db.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
            db.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))
            db.execute(delete(UserAccount).where(UserAccount.id.in_(ids)))
        db.execute(
            delete(LoginFailureState).where(
                LoginFailureState.username.like(f"{TEST_PREFIX}%")
            )
        )
        db.commit()


def force_unlock(username: str) -> None:
    """把锁定到期时间拨到过去（模拟「锁定期满」），用于验证递增档位。"""
    factory = get_session_factory()
    with factory() as db:
        db.execute(
            update(LoginFailureState)
            .where(LoginFailureState.username == username.lower())
            .values(locked_until=None)
        )
        db.commit()


def rewind_first_fail(username: str, hours: int = 25) -> None:
    """把 ``first_fail_at`` 拨回 N 小时前（模拟 24h 窗口已过）。"""
    factory = get_session_factory()
    with factory() as db:
        row = db.execute(
            select(LoginFailureState).where(
                LoginFailureState.username == username.lower()
            )
        ).scalars().first()
        if row is not None and row.first_fail_at is not None:
            row.first_fail_at = row.first_fail_at - timedelta(hours=hours)
            db.commit()


def failure_state(username: str):
    """读取失败状态行（返回 ``dict`` 或 ``None``）。"""
    factory = get_session_factory()
    with factory() as db:
        row = db.execute(
            select(LoginFailureState).where(
                LoginFailureState.username == username.lower()
            )
        ).scalars().first()
        if row is None:
            return None
        return {
            "fail_count": int(row.fail_count),
            "lock_level": int(row.lock_level),
            "locked_until": row.locked_until,
            "first_fail_at": row.first_fail_at,
        }


def account_row(username: str):
    factory = get_session_factory()
    with factory() as db:
        row = db.execute(
            select(UserAccount).where(UserAccount.username == username.lower())
        ).scalars().first()
        if row is None:
            return None
        return {
            "id": int(row.id),
            "username": row.username,
            "password_hash": row.password_hash,
            "password_algo": row.password_algo,
            "role": row.role,
            "terms_agreed_at": row.terms_agreed_at,
            "agreement_version": row.agreement_version,
        }


def session_rows(user_id: int):
    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(UserSession).where(UserSession.user_id == int(user_id))
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "access_token_id": r.access_token_id,
                "refresh_token_hash": r.refresh_token_hash,
                "revoked_at": r.revoked_at,
                "revoked_reason": r.revoked_reason,
            }
            for r in rows
        ]


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session")
def app():
    """会话级应用实例（开发环境 + 本机开发库）。"""
    application = create_app("development")
    application.config["TESTING"] = True
    # 让未捕获异常走统一 500 处理器，而不是向上抛出
    application.config["PROPAGATE_EXCEPTIONS"] = False
    # 测试装置：把邮件后端钉死为 memory（与 tests/a06 的既有做法一致）。
    # 原因：本机 backend/.env（override=True）现配置 MAIL_BACKEND=smtp 供真机联调；
    # 若不在此钉死，依赖「内存投递箱」读取验证码的用例（tests/b2 / tests/b3）会取不到
    # 验证码而失败，且测试将发起**真实 SMTP 发送**（违反「自动化测试零真实网络」）。
    application.config["MAIL_BACKEND"] = "memory"
    return application


@pytest.fixture(scope="session", autouse=True)
def _isolated_db(app):
    """运行前后快照 + 结束清理（保证不污染开发库）。

    依赖 ``app`` 装置：引擎必须在取快照前完成初始化。
    """
    before = row_counts()
    yield
    purge_test_rows()
    after = row_counts()
    assert after == before, f"测试数据未完全清理：before={before} after={after}"


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def new_account(client):
    """注册一个可用账号，返回 ``(username, password, tokens)``。"""
    username, resp = register(client)
    assert resp.status_code == 201, resp.get_json()
    return username, DEFAULT_PASSWORD, tokens_of(resp)
