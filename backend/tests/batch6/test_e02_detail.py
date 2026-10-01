# -*- coding: utf-8 -*-
"""S2 第六批 E-02（``GET /api/v1/exports/{id}``）验收用例。

覆盖：J 查询本人任务 / K 查询不存在任务 / L 查询他人任务 /
M ``pending`` / ``ready`` / ``expired`` / ``purged`` / ``failed`` 状态判定 /
凭证暴露面控制。
"""
from __future__ import annotations

import re

from tests.batch6.conftest import (
    dt_before,
    export_detail,
    insert_job,
    job_row,
    new_export,
    set_job_state,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
DETAIL_KEYS = {
    "export_id", "format", "status", "record_count", "file_token", "file_size_bytes",
    "download_expires_at", "purge_at", "downloaded_at", "created_at",
}


def _detail(client, header, export_id):
    resp = export_detail(client, header, export_id)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK"
    return body["data"]


# ════════════════════════════════════════════════════════════════════
# J —— 查询本人任务
# ════════════════════════════════════════════════════════════════════
def test_e02_detail_structure_and_token(client, exporter):
    """J：``200`` + 冻结字段；``ready`` 时返回 ``file_token``；**永不返回** ``file_path``。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    export_id = int(created["export_id"])
    data = _detail(client, exporter["header"], export_id)

    assert set(data.keys()) == DETAIL_KEYS, data
    assert data["export_id"] == export_id
    assert data["format"] == "csv"
    assert data["status"] == "ready"
    assert data["record_count"] == 3
    assert data["file_token"] == job_row(export_id)["file_token"]
    assert HEX32.match(data["file_token"])
    assert data["file_size_bytes"] > 0
    assert data["downloaded_at"] is None
    assert "file_path" not in data


def test_e02_downloaded_still_exposes_token(client, exporter):
    """M：``downloaded`` 仍在 10 分钟窗口内（契约允许**再次下载**），故仍返回凭证。"""
    from tests.batch6.conftest import download

    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    export_id = int(created["export_id"])
    token = job_row(export_id)["file_token"]
    assert download(client, exporter["header"], export_id, token).status_code == 200

    data = _detail(client, exporter["header"], export_id)
    assert data["status"] == "downloaded"
    assert data["file_token"] == token
    assert data["downloaded_at"] is not None


# ════════════════════════════════════════════════════════════════════
# M —— 状态判定（按当前时间动态判定，不依赖后台任务）
# ════════════════════════════════════════════════════════════════════
def test_e02_status_pending_hides_token(client, exporter):
    """M：``pending`` → 状态透传，且 **不下发** ``file_token``。"""
    export_id = insert_job(exporter["user_id"], status="pending")
    data = _detail(client, exporter["header"], export_id)
    assert data["status"] == "pending"
    assert data["file_token"] is None


def test_e02_status_expired_by_time(client, exporter):
    """M：``download_expires_at`` 已过 → 动态判定 ``expired`` 且不下发凭证。"""
    export_id = insert_job(
        exporter["user_id"], status="ready",
        created_at=dt_before(hours=1),
        download_expires_at=dt_before(minutes=5),
        purge_at=dt_before(days=-1),          # 尚未到强制清理时间（未来）
    )
    data = _detail(client, exporter["header"], export_id)
    assert data["status"] == "expired"
    assert data["file_token"] is None


def test_e02_status_purged_by_time(client, exporter):
    """M：``purge_at`` 已过 → 动态判定 ``purged``（优先级高于 ``expired``）。"""
    export_id = insert_job(
        exporter["user_id"], status="ready", record_count=0,
        created_at=dt_before(hours=2),
        download_expires_at=dt_before(hours=1),
        purge_at=dt_before(minutes=1),
    )
    data = _detail(client, exporter["header"], export_id)
    assert data["status"] == "purged"
    assert data["file_token"] is None


def test_e02_status_failed_passthrough(client, exporter):
    """M：``failed`` 状态透传（生成失败**不静默**），且不下发凭证。"""
    export_id = insert_job(exporter["user_id"], status="failed", record_count=None)
    data = _detail(client, exporter["header"], export_id)
    assert data["status"] == "failed"
    assert data["file_token"] is None


# ════════════════════════════════════════════════════════════════════
# K / L —— 不存在 / 他人任务
# ════════════════════════════════════════════════════════════════════
def test_e02_not_found(client, exporter):
    """K：任务不存在 → ``404 RESOURCE_NOT_FOUND``。"""
    resp = export_detail(client, exporter["header"], 987654321)
    assert resp.status_code == 404
    assert resp.get_json()["code"] == "RESOURCE_NOT_FOUND"


def test_e02_peer_cannot_read(client, exporter, peer):
    """L：非本人任务 → ``404``（**不暴露任务存在性**：与「不存在」同码同文案）。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    export_id = int(created["export_id"])

    other = export_detail(client, peer["header"], export_id)
    missing = export_detail(client, peer["header"], 987654321)

    assert other.status_code == 404 and other.get_json()["code"] == "RESOURCE_NOT_FOUND"
    assert other.get_json()["message"] == missing.get_json()["message"]
    assert "file_token" not in other.get_data(as_text=True)
    assert "file_path" not in other.get_data(as_text=True)


def test_e02_state_change_reflected(client, exporter):
    """M：状态变更（``ready`` → 窗口过期）在 E-02 立即可见。"""
    created = new_export(client, exporter["header"], format="csv",
                         password=exporter["password"])
    export_id = int(created["export_id"])
    assert _detail(client, exporter["header"], export_id)["status"] == "ready"

    set_job_state(export_id, status="expired")
    assert _detail(client, exporter["header"], export_id)["status"] == "expired"
