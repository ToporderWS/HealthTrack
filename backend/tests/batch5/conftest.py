# -*- coding: utf-8 -*-
"""S2 第五批（S 模块：首页 / 统计 / 趋势）—— **独立** pytest 公共装置。

与外层 ``tests/conftest.py``（S2 第二批封板成果）的关系：
- 复用其 ``app`` / ``client`` 装置（**不修改**该文件）；
- **本批清理范围额外覆盖** ``record_tag`` / ``health_record`` / ``health_goal``
  （外层只清 4 张账号相关表，本批必须自建覆盖，否则会话结束后残留孤儿行）；
- 每个测试**前后**都清理 ``tst`` 前缀数据，保证测试结束后恢复到 0 业务数据。

约定：
- 不回显任何口令 / Token / 密钥；
- 所有测试用户名统一 ``tst`` 前缀（与外层一致），便于统一清理；
- 测试数据**只**用 ``acctest``/``tst`` 范围，不触碰其他用户数据。
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.security import now_local
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.login_failure_state import LoginFailureState
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession

TEST_PREFIX = "tst"

#: 本批清理的表（子表在前）
B5_SCOPED_TABLES = ("record_tag", "health_record", "health_goal")

#: 8 张业务表
BUSINESS_TABLES = (
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
)

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"


# ════════════════════════════════════════════════════════════════════
# 清理
# ════════════════════════════════════════════════════════════════════
def purge_b5() -> None:
    """清理全部 ``tst`` 前缀数据（含本批的 ``record_tag`` / ``health_record`` / ``health_goal``）。"""
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
            db.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
            db.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))
            db.execute(delete(UserAccount).where(UserAccount.id.in_(ids)))
        # 兜底：清理孤儿行（用户名已不存在但记录仍在）
        # ⚠️ 旧实现为多表 ``DELETE ... FROM ... LEFT JOIN ...`` —— 引擎级「测试安全守卫」
        #    无法把它改写成 SELECT 逐行预演 ⇒ fail-closed 否决整条 DELETE
        #    （历史 572 errors 根因）。现改为**单表 DELETE + 子查询谓词**：
        #    四张表 user_id 均 NOT NULL ⇒ 语义等价；守卫可逐行预演，
        #    删除依据仍由「会话水位线 + 保护名单」在执行期强制。
        for table in B5_SCOPED_TABLES:
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


# ════════════════════════════════════════════════════════════════════
# 时间工具（窗口口径：本地日 / 周一起点）
# ════════════════════════════════════════════════════════════════════
def dt_at(day_offset: int = 0, hour: int = 8, minute: int = 0,
          second: int = 0) -> datetime:
    """本地墙上时间：今天 + ``day_offset`` 日的 ``hour:minute:second``。"""
    day = now_local().date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute, second))


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def day_str(day_offset: int = 0) -> str:
    return (now_local().date() + timedelta(days=day_offset)).isoformat()


def week_start_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ════════════════════════════════════════════════════════════════════
# 工具
# ════════════════════════════════════════════════════════════════════
def unique_username(tag: str = "") -> str:
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def user_id_by_username(username: str) -> int:
    """按用户名直查 ``user_account.id``（**不依赖**注册响应字段结构）。"""
    with get_session_factory()() as db:
        return int(
            db.execute(
                select(UserAccount.id).where(UserAccount.username == username)
            ).scalar_one()
        )


def make_user(client, tag: str = "") -> Dict[str, Any]:
    """注册一个可用账号，返回 ``{username, password, token, header, user_id}``。

    ``user_id`` **不由注册响应推导**（A-01 注册响应 ``data.user`` 不含 ``id``），
    而是按用户名回查数据库，保证拿到的恒为该账号的真实主键。
    """
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
        "user_id": user_id_by_username(username),
    }


def set_profile(client, header: Dict[str, str], **fields):
    return client.put(f"{API}/profile", headers=header, json=fields)


def post_record(client, header: Dict[str, str], payload: Dict[str, Any]):
    """R-01 便捷调用（``assert_ok`` 可显式校验）。"""
    return client.post(f"{API}/records", headers=header, json=payload)


def add_record(client, header: Dict[str, str], **payload) -> Dict[str, Any]:
    """R-01 便捷调用并断言 201，返回新建记录 ``data``。"""
    resp = post_record(client, header, payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]


def create_goal(client, header: Dict[str, str], **payload):
    return client.post(f"{API}/goals", headers=header, json=payload)


def created_goal(resp) -> Dict[str, Any]:
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["goal"]


def overview(client, header: Dict[str, str], **query):
    return client.get(f"{API}/home/overview", headers=header, query_string=query)


def trend(client, header: Dict[str, str], **query):
    return client.get(f"{API}/stats/trend", headers=header, query_string=query)


def summary(client, header: Dict[str, str], **query):
    return client.get(f"{API}/stats/summary", headers=header, query_string=query)


def payload_of(resp, status: int = 200) -> Dict[str, Any]:
    assert resp.status_code == status, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK", body
    return body["data"]


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _b5_isolated():
    """每个测试前后清理本批数据。"""
    purge_b5()
    yield
    purge_b5()


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
    """已填写档案的账号。"""
    resp = set_profile(client, user["header"], nickname="测试用户", gender=1,
                       birth_date="1995-03-18", height_cm=175.0,
                       initial_weight_kg=72.5, blood_type="O")
    assert resp.status_code == 200, resp.get_json()
    return user
