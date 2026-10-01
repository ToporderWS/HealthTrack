# -*- coding: utf-8 -*-
"""S2 第七批（D 模块：数据总览 / 清空全部数据）—— **独立** pytest 公共装置。

与外层 ``tests/conftest.py``（S2 第二批封板成果）的关系：
- 复用其 ``app`` / ``client`` 装置（**不修改**该文件）；
- **本批清理范围额外覆盖** ``health_record`` / ``record_tag`` / ``health_goal`` / ``export_job``
  （外层不管这四张表）；
- 每个测试**前后**都按 ``tst`` 前缀清理，保证测试结束后 8 张业务表恢复原状。

★ D-02 是 **destructive operation**：
- 所有用例**只**操作 ``tst`` 前缀的独立测试账号，**不得**触碰任何非测试账号；
- 断言一律"该测试账号自己的数据"，不做全库断言；
- 不回显任何口令 / Token。

造数口径：``health_record`` 走 **R-01 真实 HTTP**；``health_goal`` / ``user_profile`` 用
**直写**（仅限本批 ``tst`` 账号的行），以便精确控制 ``status`` 与 6 个健康字段。
"""
from __future__ import annotations

import os
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.security import now_local
from app.models.export_job import ExportJob
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.login_failure_state import LoginFailureState
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession

TEST_PREFIX = "tst"

#: 本批自清理涉及的表（子表在前）
B7_SCOPED_TABLES = ("record_tag", "health_record", "health_goal", "export_job")

#: 8 张业务表
BUSINESS_TABLES = (
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
)

#: ``user_profile`` 的 6 个健康字段（D-01 / D-02 口径）
HEALTH_FIELDS = ("height_cm", "initial_weight_kg", "blood_type",
                 "medical_history", "allergy_history", "medication_notes")

#: 非健康字段（D-02 必须保留）
KEEP_FIELDS = ("nickname", "gender", "birth_date")

#: 目标类型的合法单位 / 周期（仅用于直写造数，避免与 G 模块校验耦合）
GOAL_UNIT = {"weight": "kg", "water": "ml", "sport": "min", "sleep": "score"}
GOAL_PERIOD = {"weight": "once", "water": "daily", "sport": "weekly", "sleep": "daily"}

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"
DT = "%Y-%m-%d %H:%M:%S"


# ════════════════════════════════════════════════════════════════════
# 清理
# ════════════════════════════════════════════════════════════════════
def purge_b7() -> None:
    """清理 ``tst`` 前缀数据的全部关联行（**含 8 张表**；子表 → 主表）。"""
    factory = get_session_factory()
    with factory() as db:
        ids = [
            int(r[0])
            for r in db.execute(
                select(UserAccount.id).where(UserAccount.username.like(f"{TEST_PREFIX}%"))
            ).all()
        ]
        if ids:
            db.execute(delete(ExportJob).where(ExportJob.user_id.in_(ids)))
            db.execute(delete(RecordTag).where(RecordTag.user_id.in_(ids)))
            db.execute(delete(HealthRecord).where(HealthRecord.user_id.in_(ids)))
            db.execute(delete(HealthGoal).where(HealthGoal.user_id.in_(ids)))
            db.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
            db.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))
            db.execute(delete(UserAccount).where(UserAccount.id.in_(ids)))
        # 兜底：清理孤儿行（账号已不存在但记录仍在）
        # ⚠️ 旧实现为多表 ``DELETE ... FROM ... LEFT JOIN ...`` —— 引擎级「测试安全守卫」
        #    无法把它改写成 SELECT 逐行预演 ⇒ fail-closed 否决整条 DELETE
        #    （历史 572 errors 根因）。现改为**单表 DELETE + 子查询谓词**：
        #    四张表 user_id 均 NOT NULL ⇒ 语义等价；守卫可逐行预演，
        #    删除依据仍由「会话水位线 + 保护名单」在执行期强制。
        for table in B7_SCOPED_TABLES:
            db.execute(text(
                f"DELETE FROM `{table}` WHERE user_id NOT IN (SELECT id FROM user_account)"
            ))
        db.execute(
            delete(LoginFailureState).where(LoginFailureState.username.like(f"{TEST_PREFIX}%"))
        )
        db.commit()


def business_row_counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in BUSINESS_TABLES
        }


# ════════════════════════════════════════════════════════════════════
# 时间工具
# ════════════════════════════════════════════════════════════════════
def ts_before(days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """**字符串**形式（用于 HTTP 请求体 / query）。"""
    return (now_local() - timedelta(days=days, hours=hours, minutes=minutes)).strftime(DT)


def dt_before(days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    """**datetime** 形式（用于直接写 DB 的时间列）。"""
    return now_local() - timedelta(days=days, hours=hours, minutes=minutes)


# ════════════════════════════════════════════════════════════════════
# 账号
# ════════════════════════════════════════════════════════════════════
def unique_username(tag: str = "") -> str:
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def user_id_by_username(username: str) -> int:
    """按用户名直查 ``user_account.id``（**不依赖**注册响应字段结构）。"""
    with get_session_factory()() as db:
        return int(
            db.execute(select(UserAccount.id).where(UserAccount.username == username)).scalar_one()
        )


def make_user(client, tag: str = "", password: str = DEFAULT_PASSWORD) -> Dict[str, Any]:
    username = unique_username(tag)
    resp = client.post(f"{API}/auth/register", json={
        "username": username,
        "password": password,
        "agreement_version": "v1.0",
        "agreement_accepted": True,
    })
    assert resp.status_code == 201, resp.get_json()
    token = resp.get_json()["data"]["tokens"]["access_token"]
    return {
        "username": username,
        "password": password,
        "token": token,
        "header": {"Authorization": f"Bearer {token}"},
        "user_id": user_id_by_username(username),
    }


# ════════════════════════════════════════════════════════════════════
# 业务调用
# ════════════════════════════════════════════════════════════════════
def add_record(client, header: Dict[str, str], **payload) -> Dict[str, Any]:
    """R-01 新建记录（真实 HTTP）。

    返回 ``data.record``（R-01 冻结响应形如 ``{record, derived, warnings}``；
    ``record.id`` 是用户可见业务字段，本批需用它做 R-05 软删）。
    """
    resp = client.post(f"{API}/records", headers=header, json=payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["record"]


def delete_record(client, header: Dict[str, str], record_id: int):
    """R-05 软删单条记录（真实 HTTP）。"""
    return client.delete(f"{API}/records/{record_id}", headers=header)


def summary(client, header: Dict[str, str]):
    """D-01 数据总览（原始应答）。"""
    return client.get(f"{API}/me/data/summary", headers=header)


def clear(client, header: Dict[str, str], **payload):
    """D-02 清空全部数据（原始应答）。"""
    return client.post(f"{API}/me/data/clear", headers=header, json=payload)


def confirm_payload(password: str = DEFAULT_PASSWORD, **overrides) -> Dict[str, Any]:
    """D-02 三重确认的合法载荷（可按需覆盖）。"""
    body: Dict[str, Any] = {
        "confirm_text": "确认删除",
        "password": password,
        "acknowledge_irreversible": True,
    }
    body.update(overrides)
    return body


def payload_of(resp, status: int = 200) -> Dict[str, Any]:
    assert resp.status_code == status, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK", body
    return body["data"]


def body_of(resp, status: int) -> Dict[str, Any]:
    assert resp.status_code == status, (resp.status_code, resp.get_json())
    body = resp.get_json()
    assert body is not None, resp.status_code
    return body


# ════════════════════════════════════════════════════════════════════
# 直写造数 / 直查（**只动本批测试账号的行**）
# ════════════════════════════════════════════════════════════════════
def fill_profile(user_id: int, *, keep: bool = True, **fields) -> None:
    """UPSERT 档案行；``keep=True`` 时写入昵称 / 性别 / 出生日期（用于验证 D-02 保留）。"""
    with get_session_factory()() as db:
        row = db.execute(
            select(UserProfile).where(UserProfile.user_id == int(user_id))
        ).scalars().first()
        now = now_local()
        if row is None:
            row = UserProfile(user_id=int(user_id), created_at=now, updated_at=now)
            db.add(row)
        if keep:
            row.nickname = "测试昵称"
            row.gender = 1
            row.birth_date = date(1990, 5, 20)
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = now
        db.commit()


def add_goal(user_id: int, *, goal_type: str = "water", status: int = 1,
             **overrides) -> int:
    """直插一条目标（默认 ``is_deleted=0`` / ``deleted_marker=0``）。返回 ``goal_id``。

    ★ 注意 ``ck_health_goal_soft_delete``：``is_deleted = 0 OR deleted_at IS NOT NULL``
    ⇒ 构造"已软删"行时**必须**同时给 ``deleted_at``（未显式给则自动补当前时间）。
    """
    now = now_local()
    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "goal_type": goal_type,
        "period_type": GOAL_PERIOD.get(goal_type, "daily"),
        "target_value": 2000,
        "unit": GOAL_UNIT.get(goal_type, "ml"),
        "attr_1": None,
        "start_weight_kg": None,
        "start_date": now.date(),
        "target_date": None,
        "status": int(status),
        "is_deleted": 0,
        "deleted_at": None,
        "deleted_marker": 0,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    if int(payload["is_deleted"]) == 1 and payload.get("deleted_at") is None:
        payload["deleted_at"] = now          # 满足软删 CHECK 约束
    with get_session_factory()() as db:
        goal = HealthGoal(**payload)
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return int(goal.id)


def insert_job(user_id: int, **fields) -> int:
    """直插一条 ``export_job``（用于验证 D-02 **不得触碰导出任务**）。"""
    now = now_local()
    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "format": "csv",
        "metric_types": None,
        "range_start": None,
        "range_end": None,
        "status": "ready",
        "file_token": secrets.token_hex(16),
        "file_path": os.path.join("backend", "storage", "exports", "tst-b7-placeholder.csv"),
        "file_size_bytes": 100,
        "record_count": 1,
        "download_expires_at": now + timedelta(minutes=10),
        "purge_at": now + timedelta(minutes=60),
        "downloaded_at": None,
        "created_at": now,
    }
    payload.update(fields)
    with get_session_factory()() as db:
        job = ExportJob(**payload)
        db.add(job)
        db.commit()
        db.refresh(job)
        return int(job.id)


def profile_row(user_id: int) -> Optional[Dict[str, Any]]:
    with get_session_factory()() as db:
        row = db.execute(
            select(UserProfile).where(UserProfile.user_id == int(user_id))
        ).scalars().first()
        if row is None:
            return None
        out = {field: getattr(row, field) for field in HEALTH_FIELDS + KEEP_FIELDS}
        out["user_id"] = int(row.user_id)
        return out


def record_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(HealthRecord).where(HealthRecord.user_id == int(user_id))
            .order_by(HealthRecord.id.asc())
        ).scalars().all()
        return [{
            "id": int(r.id), "metric_type": r.metric_type,
            "is_deleted": int(r.is_deleted), "deleted_at": r.deleted_at,
            "recorded_at": r.recorded_at,
        } for r in rows]


def tag_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(RecordTag).where(RecordTag.user_id == int(user_id))
            .order_by(RecordTag.id.asc())
        ).scalars().all()
        return [{
            "id": int(r.id), "record_id": int(r.record_id), "tag_value": r.tag_value,
            "is_deleted": int(r.is_deleted), "deleted_at": r.deleted_at,
        } for r in rows]


def goal_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(HealthGoal).where(HealthGoal.user_id == int(user_id))
            .order_by(HealthGoal.id.asc())
        ).scalars().all()
        return [{
            "id": int(r.id), "goal_type": r.goal_type, "status": int(r.status),
            "is_deleted": int(r.is_deleted), "deleted_at": r.deleted_at,
            "deleted_marker": int(r.deleted_marker),
        } for r in rows]


def job_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(ExportJob).where(ExportJob.user_id == int(user_id))
            .order_by(ExportJob.id.asc())
        ).scalars().all()
        return [{
            "id": int(r.id), "status": r.status, "format": r.format,
            "file_path": r.file_path, "record_count": r.record_count,
        } for r in rows]


def session_rows(user_id: int) -> List[Dict[str, Any]]:
    """会话行（D-02 **不得**触碰会话）。"""
    with get_session_factory()() as db:
        rows = db.execute(
            select(UserSession).where(UserSession.user_id == int(user_id))
            .order_by(UserSession.id.asc())
        ).scalars().all()
        return [{
            "id": int(r.id), "access_token_id": r.access_token_id,
            "revoked_at": r.revoked_at, "export_pwd_fail_count": int(r.export_pwd_fail_count or 0),
        } for r in rows]


def account_row(user_id: int) -> Optional[Dict[str, Any]]:
    with get_session_factory()() as db:
        row = db.get(UserAccount, int(user_id))
        if row is None:
            return None
        return {"id": int(row.id), "username": row.username,
                "password_hash": row.password_hash, "role": row.role}


def login_failure_rows(username: str) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(LoginFailureState).where(LoginFailureState.username == str(username).lower())
        ).scalars().all()
        return [{"username": r.username, "fail_count": int(r.fail_count or 0)} for r in rows]


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _b7_isolated():
    purge_b7()
    yield
    purge_b7()


@pytest.fixture()
def user(client):
    return make_user(client)


@pytest.fixture()
def peer(client):
    return make_user(client, tag="p")


@pytest.fixture()
def rich_user(client):
    """D-01 全景账号：3 类记录（含标签、含 1 条软删）+ 2 个目标（1 in-use / 1 paused）
    + 档案 3/6 健康字段已填（昵称 / 性别 / 出生日期亦已填）。"""
    account = make_user(client, tag="r")
    add_record(client, account["header"], metric_type="weight", value_1="70.50",
               recorded_at=ts_before(days=2))
    add_record(client, account["header"], metric_type="water", value_1=500,
               recorded_at=ts_before(days=1))
    mood = add_record(client, account["header"], metric_type="mood", value_1=4,
                      recorded_at=ts_before(days=1), tags=["relaxed", "focused"])
    dropped = add_record(client, account["header"], metric_type="heart", value_1=72,
                         recorded_at=ts_before(days=3))
    resp = delete_record(client, account["header"], int(dropped["id"]))
    assert resp.status_code == 200, resp.get_json()

    add_goal(account["user_id"], goal_type="water", status=1)
    add_goal(account["user_id"], goal_type="sport", status=0)
    fill_profile(account["user_id"], height_cm="175.0", blood_type="A",
                 medication_notes="自填文本")

    account["mood_record_id"] = int(mood["id"])
    account["dropped_record_id"] = int(dropped["id"])
    return account


__all__ = [
    "API", "BUSINESS_TABLES", "DEFAULT_PASSWORD", "DT", "HEALTH_FIELDS", "KEEP_FIELDS",
    "TEST_PREFIX", "account_row", "add_goal", "add_record", "body_of", "business_row_counts",
    "clear", "confirm_payload", "delete_record", "dt_before", "fill_profile", "goal_rows",
    "insert_job", "job_rows", "login_failure_rows", "make_user", "payload_of", "profile_row",
    "purge_b7", "record_rows", "session_rows", "summary", "tag_rows", "ts_before",
    "unique_username",
]
