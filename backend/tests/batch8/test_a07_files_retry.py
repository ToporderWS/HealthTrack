# -*- coding: utf-8 -*-
"""S2 第八批 A-07 —— T4 文件处置 / 重试登记 / 事务回滚 / 日志脱敏 验收用例。

覆盖：
I ``export_job`` + **导出文件**（成功删除 / 删除失败仍 200 / 失败产生**可追踪重试登记** /
重放重试 / 路径越界保护）· K **任意第 N 步异常 → 整体 rollback**（8 张表全部原状、无半注销、
``500 INTERNAL_ERROR``、回滚后可正常注销）· 日志**脱敏**（不含 ``user_id`` / 用户名 / 完整路径 / 密码）·
C6 **重试机制实际落地方式**（``storage/cleanup_retry.jsonl`` 登记 + ``drain_cleanup_retries`` 重放）。

★ 全部用例**只**操作 ``tst`` 独立测试账号；不对任何非测试账号执行注销。
"""
from __future__ import annotations

import logging
import os

import pytest

from app.services import account_service as svc

from tests.batch8.conftest import (
    account_row,
    close_account,
    close_payload,
    goal_rows,
    job_rows,
    login_failure_rows,
    profile_row,
    read_retry_queue,
    record_rows,
    retry_queue_path,
    session_rows,
    tag_rows,
)


def _closed(client, header, password, **overrides):
    resp = close_account(client, header, **close_payload(password, **overrides))
    assert resp.status_code == 200, (resp.status_code, resp.get_json())
    return resp.get_json()


#: 注入开关（模块级，便于测试中途"恢复"删除能力）
_UNLINK_STATE = {"fail": False}


def _install_failing_unlink(monkeypatch):
    """让 ``account_service._unlink`` 抛 ``OSError``（模拟文件删除失败）。

    ★ 只替换 **account_service 模块内的删除原语**，**不触碰全局 ``os.remove``**
    （否则会连带破坏 pytest 自身的临时目录清理）。
    返回后可用 :func:`_resume_unlink` 关闭注入。
    """
    _UNLINK_STATE["fail"] = True

    def _unlink(path):  # noqa: ANN001, ANN202
        if _UNLINK_STATE["fail"]:
            raise OSError("injected disk error")
        os.remove(path)

    monkeypatch.setattr(svc, "_unlink", _unlink)


def _resume_unlink() -> None:
    """关闭删除失败注入（重放应当成功）。"""
    _UNLINK_STATE["fail"] = False


# ════════════════════════════════════════════════════════════════════
# I / T4 文件处置 —— 成功路径
# ════════════════════════════════════════════════════════════════════
def test_a07_export_file_deleted_after_commit(client, rich_user):
    """★ I（文件侧）：事务提交后导出文件被删除，且**不留重试登记**。"""
    path = rich_user["export_file"]
    assert os.path.isfile(path), "前置：导出文件存在"
    _closed(client, rich_user["header"], rich_user["password"])
    assert not os.path.isfile(path), "注销后导出文件必须被删除"
    assert read_retry_queue() == []


def test_a07_job_without_file_path_is_ok(client, app, rich_user):
    """``export_job`` 无 ``file_path``（未生成文件）→ 不影响注销成功。"""
    from tests.batch8.conftest import insert_job

    insert_job(rich_user["user_id"], file_path=None)
    body = _closed(client, rich_user["header"], rich_user["password"])
    assert body["data"] == {"account_closed": True}


def test_a07_export_file_missing_is_idempotent(client, rich_user):
    """文件已不存在（如已被清理）→ 幂等成功，**不登记重试**。"""
    os.remove(rich_user["export_file"])
    _closed(client, rich_user["header"], rich_user["password"])
    assert read_retry_queue() == []


# ════════════════════════════════════════════════════════════════════
# T4 文件处置 —— 失败路径（C6：仍 200 + 脱敏日志 + 可追踪重试登记）
# ════════════════════════════════════════════════════════════════════
def test_a07_file_delete_failure_still_returns_200(client, rich_user, monkeypatch):
    """★ T4：文件删除失败 → **仍返回 200**，数据库删除**不 rollback**。"""
    uid = rich_user["user_id"]
    _install_failing_unlink(monkeypatch)
    body = _closed(client, rich_user["header"], rich_user["password"])
    assert body["message"] == "账号已注销"
    assert body["data"] == {"account_closed": True}
    # 数据库侧仍完成（不得因文件失败而回滚）
    assert account_row(uid) is None
    assert record_rows(uid) == []
    assert job_rows(uid) == []
    assert os.path.isfile(rich_user["export_file"]), "文件仍在（删除失败）"


def test_a07_file_delete_failure_registers_retry(client, rich_user, monkeypatch):
    """★ C6：删除失败必须形成**可追踪的重试登记**（不是"以后待办"）。"""
    _install_failing_unlink(monkeypatch)
    _closed(client, rich_user["header"], rich_user["password"])
    queue = read_retry_queue()
    assert len(queue) == 1, queue
    entry = queue[0]
    assert entry["file_name"] == os.path.basename(rich_user["export_file"])
    assert int(entry["attempt"]) >= 1
    assert entry["code"] == "OSError"
    assert entry["job_id"] == rich_user["export_job_id"]


def test_a07_retry_queue_is_scrubbed(client, rich_user, monkeypatch):
    """★ 重试登记**脱敏**：只记文件名，**不含** ``user_id`` / 用户名 / 完整路径 / 密码。"""
    _install_failing_unlink(monkeypatch)
    _closed(client, rich_user["header"], rich_user["password"])
    raw = open(retry_queue_path(), "r", encoding="utf-8").read()
    assert "user_id" not in raw
    assert rich_user["username"] not in raw
    assert rich_user["password"] not in raw
    assert rich_user["export_dir"] not in raw
    assert "storage" not in raw
    entry = read_retry_queue()[0]
    assert os.sep not in str(entry["file_name"])
    assert "/" not in str(entry["file_name"])


def test_a07_retry_can_be_replayed_and_clears_queue(client, app, rich_user, monkeypatch):
    """★ C6：重放机制**真实可执行** —— 失败登记后，恢复删除能力即可清理并清空队列。"""
    path = rich_user["export_file"]
    _install_failing_unlink(monkeypatch)
    _closed(client, rich_user["header"], rich_user["password"])
    assert len(read_retry_queue()) == 1
    assert os.path.isfile(path)

    _resume_unlink()                       # 恢复删除能力（异常注入**只存在于测试**）
    with app.app_context():
        cleared, remaining = svc.drain_cleanup_retries()
    assert cleared == 1 and remaining == 0
    assert not os.path.isfile(path)
    assert read_retry_queue() == []


def test_a07_retry_attempt_increments_when_still_failing(client, app, rich_user, monkeypatch):
    """重放仍失败 → ``attempt`` 递增并**保留**登记（可追踪）。"""
    _install_failing_unlink(monkeypatch)
    _closed(client, rich_user["header"], rich_user["password"])
    with app.app_context():
        cleared, remaining = svc.drain_cleanup_retries()
    assert cleared == 0 and remaining == 1
    entry = read_retry_queue()[0]
    assert int(entry["attempt"]) >= 2


def test_a07_out_of_bound_path_is_refused(client, app, rich_user):
    """★ 安全：``file_path`` **越界**（EXPORT_DIR 之外）→ 拒绝删除该文件（只告警、不登记重试）。"""
    import tempfile

    from tests.batch8.conftest import insert_job

    outside_dir = tempfile.mkdtemp(prefix="healthtrack_b8_outside_")
    outsider = os.path.join(outside_dir, "outsider.csv")
    with open(outsider, "wb") as handle:
        handle.write(b"must-not-be-deleted")
    insert_job(rich_user["user_id"], file_path=outsider)

    _closed(client, rich_user["header"], rich_user["password"])
    assert os.path.isfile(outsider), "EXPORT_DIR 之外的文件绝不能被删除"
    assert all("outsider.csv" != e["file_name"] for e in read_retry_queue())

    # 直达函数级验证：越界必须抛 ValueError（安全拒绝）
    with app.app_context():
        try:
            svc._remove_export_file(outsider)
            refused = False
        except ValueError:
            refused = True
    assert refused, "越界路径必须被拒绝（不得删除 EXPORT_DIR 之外的文件）"
    assert os.path.isfile(outsider)


# ════════════════════════════════════════════════════════════════════
# K 事务回滚（任意第 N 步异常）
# ════════════════════════════════════════════════════════════════════
def _snapshot(rich_user):
    uid = rich_user["user_id"]
    return {
        "account": account_row(uid),
        "profile": profile_row(uid),
        "records": record_rows(uid),
        "tags": tag_rows(uid),
        "goals": goal_rows(uid),
        "sessions": session_rows(uid),
        "jobs": job_rows(uid),
        "login": login_failure_rows(rich_user["username"]),
    }


@pytest.mark.parametrize("step", [1, 2, 3, 4, 5, 6, 7, 8])
def test_a07_transaction_rolls_back_on_step_failure(client, rich_user, monkeypatch, step):
    """★ K：**任意第 N 步**数据库删除失败 → ``500 INTERNAL_ERROR`` + **整体回滚**（无半注销）。"""
    before = _snapshot(rich_user)
    original = svc._purge
    state = {"calls": 0}

    def _counting(db, model, *criteria, **kwargs):  # noqa: ANN001, ANN202
        state["calls"] += 1
        if state["calls"] == step:
            raise RuntimeError(f"injected failure at step {step}")
        return original(db, model, *criteria, **kwargs)

    monkeypatch.setattr(svc, "_purge", _counting)

    resp = close_account(client, rich_user["header"],
                         **close_payload(rich_user["password"]))
    assert resp.status_code == 500, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "INTERNAL_ERROR", body
    assert body["data"] is None

    after = _snapshot(rich_user)
    assert after == before, f"第 {step} 步失败后必须完全回滚（无半注销）"
    assert account_row(rich_user["user_id"]) is not None
    assert session_rows(rich_user["user_id"]), "会话必须保持"
    assert job_rows(rich_user["user_id"]), "导出任务必须保持"
    assert os.path.isfile(rich_user["export_file"]), "文件不得在事务内被删除"


def test_a07_rollback_then_close_succeeds(client, rich_user, monkeypatch):
    """回滚后（撤销注入）可正常完成注销。"""
    original = svc._purge

    def _boom(db, model, *criteria, **kwargs):  # noqa: ANN001, ANN202
        raise RuntimeError("injected")

    monkeypatch.setattr(svc, "_purge", _boom)
    resp = close_account(client, rich_user["header"],
                         **close_payload(rich_user["password"]))
    assert resp.status_code == 500
    assert account_row(rich_user["user_id"]) is not None

    monkeypatch.setattr(svc, "_purge", original)
    _closed(client, rich_user["header"], rich_user["password"])
    assert account_row(rich_user["user_id"]) is None


def test_a07_residue_self_check_blocks_commit(client, rich_user, monkeypatch):
    """★ C7：完整性自检未通过 → **不得 commit**，整体回滚。"""
    def _residue(db, user_id, username):  # noqa: ANN001, ANN202
        raise RuntimeError("residue detected")

    monkeypatch.setattr(svc, "_assert_no_residue", _residue)
    resp = close_account(client, rich_user["header"],
                         **close_payload(rich_user["password"]))
    assert resp.status_code == 500, resp.get_json()
    assert account_row(rich_user["user_id"]) is not None
    assert record_rows(rich_user["user_id"]), "记录必须保持"
    assert os.path.isfile(rich_user["export_file"]), "事务失败时文件不得被删除"
    assert read_retry_queue() == []


def test_a07_error_envelope_has_no_internal_details(client, rich_user, monkeypatch):
    """500 响应**不泄漏**任何内部细节（异常文本 / 表名 / SQL）。"""
    def _boom(db, model, *criteria, **kwargs):  # noqa: ANN001, ANN202
        raise RuntimeError("secret-detail-should-not-leak")

    monkeypatch.setattr(svc, "_purge", _boom)
    resp = close_account(client, rich_user["header"],
                         **close_payload(rich_user["password"]))
    raw = resp.get_data(as_text=True)
    assert "secret-detail-should-not-leak" not in raw
    assert "Traceback" not in raw
    assert "RuntimeError" not in raw


# ════════════════════════════════════════════════════════════════════
# 日志脱敏（T5 / 15.6）
# ════════════════════════════════════════════════════════════════════
def test_a07_success_log_is_scrubbed(client, rich_user, caplog):
    """成功日志含 ``account_closed`` + 条数统计；**不含**用户名 / ``user_id`` / 完整路径 / 密码。"""
    with caplog.at_level(logging.INFO, logger="app.services.account_service"):
        _closed(client, rich_user["header"], rich_user["password"])
    text = caplog.text
    assert "account_closed" in text
    assert rich_user["username"] not in text
    assert "user_id" not in text
    assert rich_user["export_dir"] not in text
    assert rich_user["password"] not in text


def test_a07_failure_log_is_scrubbed(client, rich_user, monkeypatch, caplog):
    """T4 文件删除失败日志：含结果码 / 重试次数 / job_id；**不含**用户名 / ``user_id`` / 完整路径。"""
    _install_failing_unlink(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app.services.account_service"):
        _closed(client, rich_user["header"], rich_user["password"])
    text = caplog.text
    assert "OSError" in text
    assert rich_user["username"] not in text
    assert "user_id" not in text
    assert rich_user["export_dir"] not in text
    assert rich_user["password"] not in text
