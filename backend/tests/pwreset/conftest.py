# -*- coding: utf-8 -*-
"""B1 找回密码数据层 —— pytest 装置。

设计约束（沿用 ``tests/conftest.py`` 的既有纪律）
----------------------------------------------
1. **不新建库 / 不新建表**：直接复用 ``.env.development`` 的 ``kangji_healthtrack``；
   表结构由 ``migrations/versions/0003_password_reset_email.py`` 提供（本批已升级到 0003）。
2. **测试数据自清理**：账号一律 ``tst`` 前缀；本模块结束前按 ``user_id`` 清空
   **全部 10 张表**的目标行，并断言 **10 张表行数前后一致**（不污染开发库）。
3. **不回显任何凭据**：装置不打印口令 / 验证码 / token / 邮箱明文。

> 说明：``tests/conftest.py`` 是**祖先 conftest**，其 ``app`` / ``client`` 装置与本文件
> 不冲突；本文件只补「新表的清理与计数守卫」。
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Dict

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.models import ALL_TABLES
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode

#: 与既有批次统一：测试账号一律此前缀，便于 ``scripts/b6_/b7_cleanup_testdata.py`` 兜底
TEST_PREFIX = "tst"
#: B1 **新增**的两张表（祖先 conftest 不认识 ⇒ 必须由本装置负责清理）
PW_TABLES = ("verification_code", "password_reset_token")
#: 清理范围 = 全部 10 张业务表（**不要**含 alembic_version）
GUARDED_TABLES = tuple(t for t in ALL_TABLES)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def unique_username(tag: str = "") -> str:
    """唯一测试用户名（``tst`` + tag + 6 位 hex ≤ 20 位，符合 4–20 位字母开头规则）。"""
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def max_ids() -> Dict[str, int]:
    """**全部 10 张受管表**当前的 ``MAX(id)`` 水位线（模块开始时取值）。

    ⇒ 清理只删「本模块新增」的行（``id > 水位线``），**不会**误删其它模块
    在本次运行中留下的 ``tst`` 行 —— 那些行由各自模块守卫与祖先
    ``_isolated_db`` 会话守卫负责，本装置不越界。
    """
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def purge_pw_rows(baseline_max: Dict[str, int]) -> None:
    """清理**本模块**写入的全部数据（不越界清别的模块）。

    三条路径，缺一不可：
    1. **``tst`` 前缀 + id 水位线** 定位「本模块新建」的账号 → 删其在
       ``user_session`` / ``user_profile`` / ``user_account`` 的行（子表 → 主表），
       并连带清该账号在两张新表里的行；
    2. ``login_failure_state`` 的键是 ``username``（无 user_id）⇒ 按前缀 + 水位线单独清；
    3. **按 id 水位线** 删两张新表中 ``id > baseline`` 的行 —— 覆盖「账号已被
       ``A-07`` 物理删除、仅剩孤儿子行」的情形（此时已无 ``username`` 可依）。

    ⚠️ **水位线是「不越界」的关键**（B1 实测）：若只按 ``tst`` 前缀删，则当本模块
    **不是**第一个写库的模块时（如人为把 ``tests/test_auth_flow.py`` 排在 ``pwreset``
    之前运行），会把**别的模块仍在使用的行**一起删掉 ⇒ 守卫断言 ``after == before``
    报出**假 FAIL**。加上 ``id > 水位线`` 后，本装置只回收自己造的行。
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
            db.execute(
                delete(PasswordResetToken).where(PasswordResetToken.user_id.in_(ids))
            )
            db.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
            db.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))
            db.execute(delete(UserAccount).where(UserAccount.id.in_(ids)))
        # ``login_failure_state`` 的键是 ``username``（无 user_id）⇒ 按前缀 + 水位线单独清
        db.execute(
            delete(LoginFailureState).where(
                LoginFailureState.username.like(f"{TEST_PREFIX}%"),
                LoginFailureState.id > baseline_max["login_failure_state"],
            )
        )
        # 两张新表：按 id 水位线清「本模块新增」＋「A-07 删号后留下的孤儿行」
        db.execute(
            delete(VerificationCode).where(VerificationCode.id > baseline_max["verification_code"])
        )
        db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.id > baseline_max["password_reset_token"])
        )
        db.commit()


@pytest.fixture(scope="module", autouse=True)
def _pw_scope_guard(app):  # noqa: ANN001
    """模块级守卫：运行前后对 10 张表取快照；结束清理并断言行数逐表还原。

    依赖 ``app``（祖先 conftest 的会话级装置）以确保引擎已初始化。
    """
    before = counts()
    baseline_max = max_ids()
    yield
    purge_pw_rows(baseline_max)
    after = counts()
    assert after == before, f"B1 测试数据未完全清理：before={before} after={after}"
