# -*- coding: utf-8 -*-
"""S2 第三批（P / R 模块）—— **独立** pytest 公共装置。

与外层 ``tests/conftest.py``（S2 第二批封板成果）的关系：
- 复用其 ``app`` / ``client`` 装置（**不修改**该文件）；
- **本批清理范围额外覆盖** ``health_record`` / ``record_tag``（第二批不涉及这两张表）；
- 每个测试**前后**都清理 ``tst`` 前缀数据，保证**测试结束后可恢复到 0 业务数据**。

约定：
- 不回显任何口令 / Token / 密钥；
- 所有测试用户名统一 ``tst`` 前缀（与外层一致），便于统一清理。
"""
from __future__ import annotations

import secrets
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.models.health_record import HealthRecord
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount

#: 与外层一致的测试前缀
TEST_PREFIX = "tst"
#: 本批清理的表（子表在前）
B3_TABLES_SCOPED = ("record_tag", "health_record")

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"

#: 8 张业务表
BUSINESS_TABLES = (
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
)


# ════════════════════════════════════════════════════════════════════
# 清理
# ════════════════════════════════════════════════════════════════════
def purge_b3() -> None:
    """清理全部 ``tst`` 前缀数据（含本批的 ``health_record`` / ``record_tag``）。"""
    factory = get_session_factory()
    with factory() as db:
        ids = [
            int(r[0])
            for r in db.execute(
                select(UserAccount.id).where(UserAccount.username.like(f"{TEST_PREFIX}%"))
            ).all()
        ]
        if ids:
            db.execute(delete(RecordTag).where(RecordTag.user_id.in_(ids)))
            db.execute(delete(HealthRecord).where(HealthRecord.user_id.in_(ids)))
        # 兜底：清理孤儿行（用户名已不存在但记录仍在）
        # ⚠️ 旧实现为多表 ``DELETE ... FROM ... LEFT JOIN ...`` —— 引擎级「测试安全守卫」
        #    无法把它改写成 SELECT 逐行预演 ⇒ fail-closed 否决整条 DELETE
        #    （历史 572 errors 根因）。现改为**单表 DELETE + 子查询谓词**：
        #    四张表 user_id 均 NOT NULL ⇒ 语义等价；守卫可逐行预演，
        #    删除依据仍由「会话水位线 + 保护名单」在执行期强制。
        db.execute(text(
            "DELETE FROM record_tag WHERE user_id NOT IN (SELECT id FROM user_account)"
        ))
        db.execute(text(
            "DELETE FROM health_record WHERE user_id NOT IN (SELECT id FROM user_account)"
        ))
        db.commit()


def business_row_counts() -> Dict[str, int]:
    """8 张业务表行数快照。"""
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in BUSINESS_TABLES
        }


def b3_residual() -> int:
    """本批相关表的残留行数合计（应为 0）。"""
    counts = business_row_counts()
    return counts["health_record"] + counts["record_tag"] + counts["user_account"] \
        + counts["user_profile"] + counts["user_session"] + counts["login_failure_state"]


def non_test_row_counts() -> Dict[str, int]:
    """**非测试数据**行数（归属非 ``tst`` 前缀账号的行；应恒为 0）。

    说明：``health_record`` / ``record_tag`` / ``health_goal`` / ``export_job`` 按**总量**统计
    （本批只写前两张表，且每个测试前后都会被清理）；
    账号 / 档案 / 会话 / 登录失败状态按**归属**统计，允许会话期间存在 ``tst`` 前缀行。
    """
    total_only = ("health_record", "record_tag", "health_goal", "export_job")
    owned = {
        "user_account": "SELECT COUNT(*) FROM user_account WHERE username NOT LIKE :p",
        "user_profile": ("SELECT COUNT(*) FROM user_profile up "
                         "LEFT JOIN user_account ua ON ua.id = up.user_id "
                         "WHERE ua.id IS NULL OR ua.username NOT LIKE :p"),
        "user_session": ("SELECT COUNT(*) FROM user_session us "
                         "LEFT JOIN user_account ua ON ua.id = us.user_id "
                         "WHERE ua.id IS NULL OR ua.username NOT LIKE :p"),
        "login_failure_state": ("SELECT COUNT(*) FROM login_failure_state "
                                "WHERE username NOT LIKE :p"),
    }
    out: Dict[str, int] = {}
    with get_engine().connect() as conn:
        for table in total_only:
            out[table] = int(conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0)
        for table, sql in owned.items():
            out[table] = int(conn.execute(text(sql), {"p": f"{TEST_PREFIX}%"}).scalar() or 0)
    return out


# ════════════════════════════════════════════════════════════════════
# 工具
# ════════════════════════════════════════════════════════════════════
def unique_username(tag: str = "") -> str:
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def make_user(client, tag: str = "") -> Dict[str, Any]:
    """注册一个可用账号，返回 ``{username, password, token, header}``。"""
    username = unique_username(tag)
    resp = client.post(f"{API}/auth/register", json={
        "username": username,
        "password": DEFAULT_PASSWORD,
        "agreement_version": "v1.0",
        "agreement_accepted": True,
    })
    assert resp.status_code == 201, resp.get_json()
    token = resp.get_json()["data"]["tokens"]["access_token"]
    return {
        "username": username,
        "password": DEFAULT_PASSWORD,
        "token": token,
        "header": {"Authorization": f"Bearer {token}"},
    }


def post_record(client, header: Dict[str, str], payload: Dict[str, Any],
                idem: Optional[str] = None):
    """R-01 便捷调用。"""
    headers = dict(header)
    if idem:
        headers["Idempotency-Key"] = idem
    return client.post(f"{API}/records", headers=headers, json=payload)


def created_record(resp) -> Dict[str, Any]:
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["record"]


def set_profile(client, header: Dict[str, str], **fields):
    """P-02 便捷调用。"""
    return client.put(f"{API}/profile", headers=header, json=fields)


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _b3_isolated():
    """每个测试前后清理本批数据（含 ``health_record`` / ``record_tag``）。"""
    purge_b3()
    yield
    purge_b3()


@pytest.fixture()
def user(client):
    """一个已注册账号（含 Token）。"""
    return make_user(client)


@pytest.fixture()
def peer(client):
    """另一个账号（用于跨用户隔离验证）。"""
    return make_user(client, tag="p")


@pytest.fixture()
def ready_user(client, user):
    """已填写身高 / 初始体重的账号（便于验证 BMI 派生）。"""
    resp = set_profile(client, user["header"], nickname="测试用户", gender=1,
                       birth_date="1995-03-18", height_cm=175.0,
                       initial_weight_kg=72.5, blood_type="O")
    assert resp.status_code == 200, resp.get_json()
    return user
