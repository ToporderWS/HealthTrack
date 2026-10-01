# -*- coding: utf-8 -*-
"""S2 第四批（G 模块：健康目标）—— **独立** pytest 公共装置。

与外层 ``tests/conftest.py``（S2 第二批封板成果）的关系：
- 复用其 ``app`` / ``client`` 装置（**不修改**该文件）；
- **本批清理范围额外覆盖** ``health_goal``（第三批的 ``purge_b3`` **不含**该表，
  本批必须自建覆盖，否则每测残留 + 会话结束后会成为孤儿行）；
- 每个测试**前后**都清理 ``tst`` 前缀数据，保证测试结束后可恢复到 0 业务数据。

约定：
- 不回显任何口令 / Token / 密钥；
- 所有测试用户名统一 ``tst`` 前缀（与外层一致），便于统一清理。
"""
from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.security import now_local
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount

#: 与外层一致的测试前缀
TEST_PREFIX = "tst"
#: 本批清理的表（子表在前）
B4_TABLES_SCOPED = ("record_tag", "health_record", "health_goal")

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
def purge_b4() -> None:
    """清理全部 ``tst`` 前缀数据（含本批的 ``health_goal``）。"""
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
            db.execute(delete(HealthGoal).where(HealthGoal.user_id.in_(ids)))
        # 兜底：清理孤儿行（用户名已不存在但记录仍在）
        # ⚠️ 旧实现为多表 ``DELETE ... FROM ... LEFT JOIN ...`` —— 引擎级「测试安全守卫」
        #    无法把它改写成 SELECT 逐行预演 ⇒ fail-closed 否决整条 DELETE
        #    （历史 572 errors 根因）。现改为**单表 DELETE + 子查询谓词**：
        #    四张表 user_id 均 NOT NULL ⇒ 语义等价；守卫可逐行预演，
        #    删除依据仍由「会话水位线 + 保护名单」在执行期强制。
        for table in ("record_tag", "health_record", "health_goal"):
            db.execute(text(
                f"DELETE FROM `{table}` WHERE user_id NOT IN (SELECT id FROM user_account)"
            ))
        db.commit()


def business_row_counts() -> Dict[str, int]:
    """8 张业务表行数快照。"""
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in BUSINESS_TABLES
        }


def non_test_row_counts() -> Dict[str, int]:
    """**非测试数据**行数（归属非 ``tst`` 前缀账号的行；应恒为 0）。"""
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
# 时间工具（G-07 窗口口径：按服务器本地日 / 周一起点）
# ════════════════════════════════════════════════════════════════════
def dt_at(day_offset: int = 0, hour: int = 8, minute: int = 0) -> datetime:
    """本地墙上时间：今天 + ``day_offset`` 日的 ``hour:minute``。"""
    day = now_local().date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute))


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def week_start_offset() -> int:
    """本周一相对今天的偏移（今天为周一时为 0，其余为负）。"""
    return -now_local().date().weekday()


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


def set_profile(client, header: Dict[str, str], **fields):
    """P-02 便捷调用。"""
    return client.put(f"{API}/profile", headers=header, json=fields)


def post_record(client, header: Dict[str, str], payload: Dict[str, Any]):
    """R-01 便捷调用。"""
    return client.post(f"{API}/records", headers=header, json=payload)


def create_goal(client, header: Dict[str, str], **payload):
    """G-02 便捷调用。"""
    return client.post(f"{API}/goals", headers=header, json=payload)


def created_goal(resp) -> Dict[str, Any]:
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["goal"]


def goal_row(goal_id: int) -> Optional[Dict[str, Any]]:
    """直查 ``health_goal`` 物理行（用于软删三件事的强制核验）。"""
    with get_session_factory()() as db:
        row = db.get(HealthGoal, int(goal_id))
        if row is None:
            return None
        return {
            "id": int(row.id),
            "user_id": int(row.user_id),
            "goal_type": row.goal_type,
            "period_type": row.period_type,
            "target_value": row.target_value,
            "unit": row.unit,
            "attr_1": row.attr_1,
            "start_weight_kg": row.start_weight_kg,
            "start_date": row.start_date,
            "target_date": row.target_date,
            "status": int(row.status),
            "is_deleted": int(row.is_deleted),
            "deleted_at": row.deleted_at,
            "deleted_marker": int(row.deleted_marker),
        }


def insert_conflicting_active_goal(user_id: int, goal_type: str) -> int:
    """**仅供防御性分支测试**：直接写入第二条"未软删"目标。

    唯一约束 ``uk_goal_user_type_active(user_id, goal_type, deleted_marker)`` 使
    ``deleted_marker = 0`` 的同类型行只能有 1 条，因此「恢复时同类已在用 → 409」
    在正常业务路径下**不可自然构造**；本函数用**非零** ``deleted_marker`` 绕过约束，
    以验证该**防御性分支**确实生效。
    """
    now = now_local()
    with get_session_factory()() as db:
        row = HealthGoal(
            user_id=int(user_id), goal_type=goal_type, period_type="daily",
            target_value=2000, unit="ml", attr_1=None, start_weight_kg=None,
            start_date=now.date(), target_date=None, status=1,
            is_deleted=0, deleted_marker=999999, created_at=now, updated_at=now,
        )
        db.add(row)
        db.commit()
        return int(row.id)


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _b4_isolated():
    """每个测试前后清理本批数据（含 ``health_goal``）。"""
    purge_b4()
    yield
    purge_b4()


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
    """已填写身高 / 初始体重的账号。"""
    resp = set_profile(client, user["header"], nickname="测试用户", gender=1,
                       birth_date="1995-03-18", height_cm=175.0,
                       initial_weight_kg=72.5, blood_type="O")
    assert resp.status_code == 200, resp.get_json()
    return user
