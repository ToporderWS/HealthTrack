# -*- coding: utf-8 -*-
"""S2 第六批（E 模块：数据导出）—— **独立** pytest 公共装置。

与外层 ``tests/conftest.py``（S2 第二批封板成果）的关系：
- 复用其 ``app`` / ``client`` 装置（**不修改**该文件）；
- **本批清理范围额外覆盖** ``export_job``（外层不管此表）；
- 每个测试**前后**都清理 ``tst`` 前缀数据，保证测试结束后业务表恢复原状；
- **导出文件会话级隔离**（OPEN-TI-1-B）：测试期 ``EXPORT_DIR`` 被覆盖为系统临时目录，
  产物**绝不写入** ``backend/storage/exports/``，也不依赖任何「运行后删除」动作。

约定：
- 不回显任何口令 / Token / 密钥 / 下载凭证；
- 所有测试用户名统一 ``tst`` 前缀；测试数据**只**用本批 ``tst`` 范围。
"""
from __future__ import annotations

import os
import secrets
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import delete, select, text, update

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

#: 本批自清理的表（子表在前）
B6_SCOPED_TABLES = ("record_tag", "health_record", "health_goal", "export_job")

#: 8 张业务表
BUSINESS_TABLES = (
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
)

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"
DT = "%Y-%m-%d %H:%M:%S"


# ════════════════════════════════════════════════════════════════════
# 导出目录与文件
# ════════════════════════════════════════════════════════════════════
#: 本次运行**实际生效**的导出根目录（测试期由 :func:`_b6_export_dir` 覆盖；期外为 ``None``）。
_CURRENT_EXPORT_DIR: Optional[str] = None


def export_dir() -> str:
    """返回本批**实际生效**的 ``EXPORT_DIR``。

    OPEN-TI-1-B：测试期内由 :func:`_b6_export_dir` 覆盖为**会话临时目录**；
    产品侧同源 —— ``app.config`` 的 ``EXPORT_DIR`` 被同步覆盖，而
    ``export_service.export_dir()`` 读的正是 ``current_app.config``。
    """
    if _CURRENT_EXPORT_DIR:
        return _CURRENT_EXPORT_DIR
    from app.core.config import load_config

    return str(load_config("development").get("EXPORT_DIR") or "")


def export_filenames() -> List[str]:
    base = export_dir()
    if not os.path.isdir(base):
        return []
    return sorted(os.listdir(base))


# ════════════════════════════════════════════════════════════════════
# 清理
# ════════════════════════════════════════════════════════════════════
def purge_b6() -> None:
    """清理 ``tst`` 前缀数据（含 ``export_job``）。

    OPEN-TI-1-B：导出文件已由**会话临时目录**隔离（见 :func:`b6_export_dir`），
    本函数**不再**触碰任何 ``EXPORT_DIR`` 文件 —— 无删除路线，与沙箱删除配额彻底解耦。
    """
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
        for table in B6_SCOPED_TABLES:
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
def day_before(days: int) -> str:
    return (now_local() - timedelta(days=days)).strftime("%Y-%m-%d")


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
    resp = client.post(f"{API}/records", headers=header, json=payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]


def post_export(client, header: Dict[str, str], **payload):
    return client.post(f"{API}/exports", headers=header, json=payload)


def new_export(client, header: Dict[str, str], *, unblock: bool = False,
               **payload) -> Dict[str, Any]:
    """创建导出任务并断言 ``202``；``unblock=True`` 时把任务置为 ``downloaded``。

    ``downloaded`` 不属「进行中」（``pending`` / ``ready``），因此不再阻塞后续导出
    —— 便于在同一个账号上连续造多个任务。
    """
    resp = post_export(client, header, **payload)
    assert resp.status_code == 202, resp.get_json()
    data = resp.get_json()["data"]
    if unblock:
        set_job_state(int(data["export_id"]), status="downloaded")
    return data


def export_detail(client, header: Dict[str, str], export_id: int):
    return client.get(f"{API}/exports/{export_id}", headers=header)


def download(client, header: Dict[str, str], export_id: int, file_token: Optional[str]):
    url = f"{API}/exports/{export_id}/download"
    if file_token is not None:
        url = f"{url}?file_token={file_token}"
    return client.get(url, headers=header)


def list_exports(client, header: Dict[str, str], **query):
    return client.get(f"{API}/exports", headers=header, query_string=query)


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
# 任务直查 / 状态模拟（**只动本批测试产生的行**）
# ════════════════════════════════════════════════════════════════════
def job_row(export_id: int) -> Dict[str, Any]:
    with get_session_factory()() as db:
        job = db.get(ExportJob, int(export_id))
        assert job is not None, f"export_job 不存在：{export_id}"
        return {
            "id": int(job.id), "user_id": int(job.user_id), "format": job.format,
            "metric_types": job.metric_types, "status": job.status,
            "file_token": job.file_token, "file_path": job.file_path,
            "file_size_bytes": job.file_size_bytes, "record_count": job.record_count,
            "download_expires_at": job.download_expires_at, "purge_at": job.purge_at,
            "downloaded_at": job.downloaded_at, "created_at": job.created_at,
        }


def set_job_state(export_id: int, **fields) -> None:
    """直接更新任务状态（用于模拟 ``pending`` / ``expired`` / ``purged`` / 过期窗口）。"""
    with get_session_factory()() as db:
        db.execute(update(ExportJob).where(ExportJob.id == int(export_id)).values(**fields))
        db.commit()


def export_fail_count(user_id: int) -> int:
    """当前会话的导出验密失败计数（取该用户**最近一条未失效会话**）。"""
    with get_session_factory()() as db:
        rows = db.execute(
            select(UserSession.export_pwd_fail_count)
            .where(UserSession.user_id == int(user_id), UserSession.revoked_at.is_(None))
            .order_by(UserSession.id.desc())
        ).all()
        assert rows, "未找到未失效会话"
        return int(rows[0][0])


def insert_job(user_id: int, **fields) -> int:
    """**直插**一条 ``export_job``（供 E-04 分页 / 状态矩阵用例构造数据，绕过 HTTP 与验密）。"""
    now = now_local()
    payload = {
        "user_id": int(user_id),
        "format": "csv",
        "metric_types": None,
        "range_start": None,
        "range_end": None,
        "status": "ready",
        "file_token": secrets.token_hex(16),
        "file_path": None,
        "file_size_bytes": 0,
        "record_count": 0,
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


def export_file_bytes(export_id: int) -> bytes:
    row = job_row(export_id)
    path = row["file_path"]
    assert path and os.path.isfile(path), f"导出文件不存在：{path}"
    with open(str(path), "rb") as handle:
        return handle.read()


# ════════════════════════════════════════════════════════════════════
# 装置
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session")
def b6_export_dir():
    """本批测试专用 ``EXPORT_DIR``（**系统临时目录**；绝不触碰项目内 ``storage``）。

    参照 ``tests/batch8/conftest.py`` 既有先例：把导出根指向系统临时目录，
    测试产生的 csv/json **从一开始就只写入临时目录**，不依赖任何「运行后删除」动作，
    从而与沙箱「单轮累计删除阈值」**彻底解耦**。

    ★ 不使用 pytest 的 ``tmp_path`` / ``tmp_path_factory``：其会话结束清理走
    ``shutil.rmtree``，在本机沙箱下会触发**批量删除守卫**（与测试无关的环境限制）。
    """
    root = tempfile.mkdtemp(prefix="healthtrack_b6_")
    target = os.path.join(root, "exports")
    os.makedirs(target, exist_ok=True)
    return target


@pytest.fixture(autouse=True)
def _b6_export_dir(app, b6_export_dir, monkeypatch):
    """把**当前应用**的 ``EXPORT_DIR`` 覆盖为会话临时目录（测试结束自动还原）。

    必须覆盖 ``app.config`` —— 产品 ``export_service.export_dir()`` 读的是
    ``current_app.config.get("EXPORT_DIR")``；只改测试侧变量**不会生效**。
    """
    global _CURRENT_EXPORT_DIR

    monkeypatch.setitem(app.config, "EXPORT_DIR", b6_export_dir)
    _CURRENT_EXPORT_DIR = b6_export_dir
    yield b6_export_dir
    _CURRENT_EXPORT_DIR = None


@pytest.fixture(autouse=True)
def _b6_isolated(_b6_export_dir):
    purge_b6()
    yield
    purge_b6()


@pytest.fixture()
def user(client):
    return make_user(client)


@pytest.fixture()
def peer(client):
    return make_user(client, tag="p")


@pytest.fixture()
def exporter(client, user):
    """已写入 3 条健康记录（weight / water / mood）的账号。"""
    add_record(client, user["header"], metric_type="weight", value_1="70.50",
               recorded_at=ts_before(days=2))
    add_record(client, user["header"], metric_type="water", value_1=500,
               recorded_at=ts_before(days=1))
    add_record(client, user["header"], metric_type="mood", value_1=4,
               recorded_at=ts_before(days=1), tags=["relaxed", "focused"])
    return user


__all__ = [
    "API", "DEFAULT_PASSWORD", "TEST_PREFIX",
    "add_record", "body_of", "business_row_counts", "day_before",
    "download", "export_detail", "export_dir", "export_file_bytes", "export_filenames",
    "insert_job", "job_row", "list_exports", "make_user", "new_export", "payload_of",
    "post_export", "purge_b6", "set_job_state",
    "ts_before", "unique_username",
]
