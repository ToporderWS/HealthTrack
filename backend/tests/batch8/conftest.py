# -*- coding: utf-8 -*-
"""S2 第八批（A-07 注销账号）—— **独立** pytest 公共装置。

与外层 ``tests/conftest.py``（S2 第二批封板成果）的关系：
- 复用其 ``app`` / ``client`` 装置（**不修改**该文件）；
- 本批清理范围覆盖 **8 张业务表** + ``storage/cleanup_retry.jsonl``；
- 每个测试**前后**都按 ``tst`` 前缀清理，保证测试结束后业务库恢复原状。

★ A-07 是 **destructive operation**（物理删除 8 张表的目标账号数据）：
- 所有用例**只**操作 ``tst`` 前缀的独立测试账号，**不得**触碰任何非测试账号；
- 断言一律"该测试账号自己的数据"（+ 对端账号不受影响），不做全库断言；
- 不回显任何口令 / Token / 完整导出路径。

造数口径：``health_record`` 走 **R-01 真实 HTTP**；``user_profile`` / ``health_goal`` /
``login_failure_state`` / ``user_session`` / ``export_job`` 用**直写**
（仅限本批 ``tst`` 账号的行），以便精确控制软删行、锁定状态、多设备会话与导出文件。
"""
from __future__ import annotations

import os
import secrets
import tempfile
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
from app.services import account_service

TEST_PREFIX = "tst"

#: 8 张业务表（A-07 必须级联物理删除其中的目标账号数据）
BUSINESS_TABLES = (
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
)

#: ``user_profile`` 6 个健康字段
HEALTH_FIELDS = ("height_cm", "initial_weight_kg", "blood_type",
                 "medical_history", "allergy_history", "medication_notes")
#: 档案的非健康字段
KEEP_FIELDS = ("nickname", "gender", "birth_date")

GOAL_UNIT = {"weight": "kg", "water": "ml", "sport": "min", "sleep": "score"}
GOAL_PERIOD = {"weight": "once", "water": "daily", "sport": "weekly", "sleep": "daily"}

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"
DT = "%Y-%m-%d %H:%M:%S"

#: 本批装置创建的导出文件前缀（用于 ``EXPORT_DIR`` 的**精确前缀清理**）
EXPORT_FILE_PREFIX = "tstb8_"

#: A-07 确认文字（**独立于 D-02 的「确认删除」**）
CONFIRM_TEXT = "注销账号"


# ════════════════════════════════════════════════════════════════════
# 清理
# ════════════════════════════════════════════════════════════════════
#: 当前生效的导出根（由 ``_b8_export_dir`` 装置设置）—— 使本模块辅助函数在
#: **无 app context** 时也能定位重试登记文件
_CURRENT_EXPORT_DIR: Optional[str] = None


def retry_queue_path(application=None) -> str:
    """``cleanup_retry.jsonl``（与 ``EXPORT_DIR`` 同级）。"""
    base = application.config.get("EXPORT_DIR") if application is not None else None
    if not base:
        base = _CURRENT_EXPORT_DIR
    if not base:
        try:
            from flask import current_app

            base = current_app.config.get("EXPORT_DIR")
        except RuntimeError:
            base = None
    if not base:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "storage", "exports")
    return os.path.join(os.path.dirname(os.path.realpath(base)), "cleanup_retry.jsonl")


def purge_b8(application=None) -> None:
    """清理 ``tst`` 前缀数据的全部关联行（**含 8 张表**；子表 → 主表）+ 重试登记文件。"""
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
        # 兜底：孤儿行（账号已不存在但记录仍在）
        # ⚠️ 旧实现为多表 ``DELETE ... FROM ... LEFT JOIN ...`` —— 引擎级「测试安全守卫」
        #    无法把它改写成 SELECT 逐行预演 ⇒ fail-closed 否决整条 DELETE
        #    （历史 572 errors 根因）。现改为**单表 DELETE + 子查询谓词**：
        #    四张表 user_id 均 NOT NULL ⇒ 语义等价；守卫可逐行预演，
        #    删除依据仍由「会话水位线 + 保护名单」在执行期强制。
        for table in ("record_tag", "health_record", "health_goal", "export_job"):
            db.execute(text(
                f"DELETE FROM `{table}` WHERE user_id NOT IN (SELECT id FROM user_account)"
            ))
        db.execute(
            delete(LoginFailureState).where(
                LoginFailureState.username.like(f"{TEST_PREFIX}%")
            )
        )
        db.commit()
    queue = retry_queue_path(application)
    if os.path.isfile(queue):
        os.remove(queue)


def business_row_counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in BUSINESS_TABLES
        }


# ════════════════════════════════════════════════════════════════════
# 时间 / 账号
# ════════════════════════════════════════════════════════════════════
def ts_before(days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    return (now_local() - timedelta(days=days, hours=hours, minutes=minutes)).strftime(DT)


def unique_username(tag: str = "") -> str:
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def user_id_by_username(username: str) -> int:
    with get_session_factory()() as db:
        return int(
            db.execute(
                select(UserAccount.id).where(UserAccount.username == str(username).lower())
            ).scalar_one()
        )


def make_user(client, tag: str = "", password: str = DEFAULT_PASSWORD) -> Dict[str, Any]:
    """注册独立测试账号；返回口令 / 双 Token / 请求头 / ``user_id``。"""
    username = unique_username(tag)
    resp = client.post(f"{API}/auth/register", json={
        "username": username,
        "password": password,
        "agreement_version": "v1.0",
        "agreement_accepted": True,
    })
    assert resp.status_code == 201, resp.get_json()
    tokens = resp.get_json()["data"]["tokens"]
    return {
        "username": username,
        "password": password,
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "header": {"Authorization": f"Bearer {tokens['access_token']}"},
        "user_id": user_id_by_username(username),
    }


# ════════════════════════════════════════════════════════════════════
# 业务调用
# ════════════════════════════════════════════════════════════════════
def close_account(client, header: Dict[str, str], **payload):
    """A-07 注销账号（原始应答）。"""
    return client.delete(f"{API}/users/me", headers=header, json=payload)


def close_payload(password: str = DEFAULT_PASSWORD, **overrides) -> Dict[str, Any]:
    """A-07 三重确认的合法载荷（``confirm_text`` 固定「注销账号」；**无 ack 参数**）。"""
    body: Dict[str, Any] = {"password": password, "confirm_text": CONFIRM_TEXT}
    body.update(overrides)
    return body


def add_record(client, header: Dict[str, str], **payload) -> Dict[str, Any]:
    """R-01 新建记录（真实 HTTP）；返回 ``data.record``。"""
    resp = client.post(f"{API}/records", headers=header, json=payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["record"]


def delete_record(client, header: Dict[str, str], record_id: int):
    """R-05 软删单条记录（真实 HTTP）。"""
    return client.delete(f"{API}/records/{record_id}", headers=header)


def body_of(resp, status: int) -> Dict[str, Any]:
    assert resp.status_code == status, (resp.status_code, resp.get_json())
    body = resp.get_json()
    assert body is not None, resp.status_code
    return body


# ════════════════════════════════════════════════════════════════════
# 直写造数（**只动本批测试账号的行**）
# ════════════════════════════════════════════════════════════════════
def fill_profile(user_id: int, *, keep: bool = True, **fields) -> None:
    """UPSERT 档案行（``keep=True`` 时写昵称 / 性别 / 出生日期）。"""
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
    """直插一条目标；构造软删行时自动补 ``deleted_at``（满足 CHECK 约束）。"""
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
        payload["deleted_at"] = now
    with get_session_factory()() as db:
        goal = HealthGoal(**payload)
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return int(goal.id)


def insert_job(user_id: int, **fields) -> int:
    """直插一条 ``export_job``（A-07 必须物理删除；删除前需取其 ``file_path``）。"""
    now = now_local()
    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "format": "csv",
        "metric_types": None,
        "range_start": None,
        "range_end": None,
        "status": "ready",
        "file_token": secrets.token_hex(16),
        "file_path": None,
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


def write_export_file(export_dir: str, content: bytes = b"a,b\r\n1,2\r\n") -> str:
    """在 ``EXPORT_DIR`` 下写一个**服务端命名**的导出文件，返回绝对路径。

    ★ 文件名带 ``tstb8_`` 前缀：使测试产物**可被识别**（本批导出根为系统临时目录，
    因此项目内 ``backend/storage/exports`` 全流程保持 0 文件）。
    """
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, f"{EXPORT_FILE_PREFIX}{secrets.token_hex(16)}.csv")
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def add_login_failure(username: str, *, fail_count: int = 3, lock_level: int = 1) -> None:
    """直插一条登录失败状态（A-07 必须**按 username** 物理删除）。"""
    now = now_local()
    with get_session_factory()() as db:
        db.add(LoginFailureState(
            username=str(username).lower(),
            fail_count=int(fail_count),
            first_fail_at=now,
            locked_until=now + timedelta(minutes=5),
            lock_level=int(lock_level),
            updated_at=now,
        ))
        db.commit()


def add_extra_session(user_id: int, *, revoked: bool = False) -> int:
    """直插一条会话（模拟**另一台设备**；A-07 必须删除**全部**会话）。"""
    now = now_local()
    with get_session_factory()() as db:
        row = UserSession(
            user_id=int(user_id),
            refresh_token_hash=secrets.token_hex(32),
            access_token_id=secrets.token_hex(16),
            access_expires_at=now + timedelta(hours=2),
            refresh_expires_at=now + timedelta(days=30),
            revoked_at=(now if revoked else None),
            revoked_reason=("logout" if revoked else None),
            created_at=now,
            last_used_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)


# ════════════════════════════════════════════════════════════════════
# 直查
# ════════════════════════════════════════════════════════════════════
def account_row(user_id: int) -> Optional[Dict[str, Any]]:
    with get_session_factory()() as db:
        row = db.get(UserAccount, int(user_id))
        if row is None:
            return None
        return {"id": int(row.id), "username": row.username,
                "password_hash": row.password_hash, "role": row.role}


def account_by_username(username: str) -> Optional[Dict[str, Any]]:
    with get_session_factory()() as db:
        row = db.execute(
            select(UserAccount).where(UserAccount.username == str(username).lower())
        ).scalars().first()
        if row is None:
            return None
        return {"id": int(row.id), "username": row.username}


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
        return [{"id": int(r.id), "metric_type": r.metric_type,
                 "is_deleted": int(r.is_deleted), "deleted_at": r.deleted_at} for r in rows]


def tag_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(RecordTag).where(RecordTag.user_id == int(user_id))
            .order_by(RecordTag.id.asc())
        ).scalars().all()
        return [{"id": int(r.id), "record_id": int(r.record_id), "tag_value": r.tag_value,
                 "is_deleted": int(r.is_deleted), "deleted_at": r.deleted_at} for r in rows]


def goal_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(HealthGoal).where(HealthGoal.user_id == int(user_id))
            .order_by(HealthGoal.id.asc())
        ).scalars().all()
        return [{"id": int(r.id), "goal_type": r.goal_type, "status": int(r.status),
                 "is_deleted": int(r.is_deleted), "deleted_at": r.deleted_at,
                 "deleted_marker": int(r.deleted_marker)} for r in rows]


def job_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(ExportJob).where(ExportJob.user_id == int(user_id))
            .order_by(ExportJob.id.asc())
        ).scalars().all()
        return [{"id": int(r.id), "status": r.status, "file_path": r.file_path,
                 "record_count": r.record_count} for r in rows]


def session_rows(user_id: int) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(UserSession).where(UserSession.user_id == int(user_id))
            .order_by(UserSession.id.asc())
        ).scalars().all()
        return [{"id": int(r.id), "access_token_id": r.access_token_id,
                 "revoked_at": r.revoked_at, "export_pwd_fail_count": int(r.export_pwd_fail_count or 0),
                 "change_pwd_fail_count": int(r.change_pwd_fail_count or 0)} for r in rows]


def login_failure_rows(username: str) -> List[Dict[str, Any]]:
    with get_session_factory()() as db:
        rows = db.execute(
            select(LoginFailureState).where(
                LoginFailureState.username == str(username).lower()
            )
        ).scalars().all()
        return [{"username": r.username, "fail_count": int(r.fail_count or 0),
                 "lock_level": int(r.lock_level or 0)} for r in rows]


def read_retry_queue(application=None) -> List[Dict[str, Any]]:
    """读取重试登记队列（每行一个 JSON 对象）。"""
    path = retry_queue_path(application)
    if not os.path.isfile(path):
        return []
    import json

    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text_line = line.strip()
            if not text_line:
                continue
            try:
                entry = json.loads(text_line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                items.append(entry)
    return items


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session")
def b8_export_dir():
    """本批测试专用 ``EXPORT_DIR``（**系统临时目录**；绝不触碰项目内 ``storage``）。

    A-07 的 T4 会真实删除导出文件；把导出根指向系统临时目录，既能覆盖真实文件行为，
    又不会在项目目录内产生任何测试副作用。

    ★ 不使用 pytest 的 ``tmp_path`` / ``tmp_path_factory``：其会话结束清理走
    ``shutil.rmtree``，在本机沙箱下会触发**批量删除守卫**（与测试无关的环境限制）。
    """
    root = tempfile.mkdtemp(prefix="healthtrack_b8_")
    target = os.path.join(root, "exports")
    os.makedirs(target, exist_ok=True)
    return target


@pytest.fixture(autouse=True)
def _b8_export_dir(app, b8_export_dir, monkeypatch):
    """把当前应用的 ``EXPORT_DIR`` 覆盖为临时目录（测试结束自动还原）。"""
    global _CURRENT_EXPORT_DIR

    monkeypatch.setitem(app.config, "EXPORT_DIR", b8_export_dir)
    _CURRENT_EXPORT_DIR = b8_export_dir
    yield b8_export_dir
    _CURRENT_EXPORT_DIR = None


@pytest.fixture(autouse=True)
def _b8_isolated(app, _b8_export_dir):
    """每个测试前后按 ``tst`` 前缀清理（含重试登记文件与本批导出文件）。"""
    purge_b8(app)
    yield
    purge_b8(app)


@pytest.fixture()
def user(client):
    return make_user(client)


@pytest.fixture()
def peer(client):
    return make_user(client, tag="p")


@pytest.fixture()
def rich_user(app, client):
    """A-07 全景账号：8 张表**全部**都有目标账号数据。

    - ``health_record``：3 条活跃（weight / water / mood，mood 带 2 个标签）+ 1 条**已软删**；
    - ``record_tag``：mood 的 2 个活跃标签；
    - ``health_goal``：2 条（water 活跃 / sport **已软删**）；
    - ``user_profile``：6 个健康字段**全填** + 昵称 / 性别 / 出生日期；
    - ``user_session``：注册会话 + **1 条额外设备会话**；
    - ``login_failure_state``：1 行（按 username）；
    - ``export_job``：1 条 + ``EXPORT_DIR`` 下**真实导出文件**。
    """
    account = make_user(client, tag="r")
    export_dir = str(app.config.get("EXPORT_DIR") or "")

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
    add_goal(account["user_id"], goal_type="sport", status=1,
             is_deleted=1, deleted_marker=0)          # 已软删目标（CHECK：自动补 deleted_at）
    fill_profile(account["user_id"],
                 height_cm="175.0", initial_weight_kg="72.5", blood_type="O",
                 medical_history="自填文本", allergy_history="自填文本",
                 medication_notes="自填文本")
    add_login_failure(account["username"])
    extra_session_id = add_extra_session(account["user_id"])

    export_file = write_export_file(export_dir)
    job_id = insert_job(account["user_id"], file_path=export_file)

    account.update({
        "export_dir": export_dir,
        "export_file": export_file,
        "export_job_id": job_id,
        "extra_session_id": extra_session_id,
        "mood_record_id": int(mood["id"]),
        "dropped_record_id": int(dropped["id"]),
    })
    return account


__all__ = [
    "API", "BUSINESS_TABLES", "CONFIRM_TEXT", "DEFAULT_PASSWORD", "DT",
    "HEALTH_FIELDS", "KEEP_FIELDS", "TEST_PREFIX",
    "account_by_username", "account_row", "add_extra_session", "add_goal",
    "add_login_failure", "add_record", "body_of", "business_row_counts",
    "close_account", "close_payload", "delete_record", "fill_profile",
    "goal_rows", "insert_job", "job_rows", "login_failure_rows", "make_user",
    "profile_row", "purge_b8", "read_retry_queue", "record_rows",
    "retry_queue_path", "session_rows", "tag_rows", "ts_before",
    "unique_username", "user_id_by_username", "write_export_file",
]
