# -*- coding: utf-8 -*-
"""S2 第六批 E-03（``GET /api/v1/exports/{id}/download``）验收用例。

覆盖：N 合法下载 / O 非法 ``file_token`` / P 他人任务下载 / Q ``expired`` / ``purged`` 限制 /
R 目录穿越与路径注入 / 重复下载幂等（``downloaded_at`` 仅首次）。
"""
from __future__ import annotations

import os
import re

from tests.batch6.conftest import (
    dt_before,
    download,
    export_dir,
    export_file_bytes,
    job_row,
    new_export,
    set_job_state,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")
DISPOSITION = re.compile(r'^attachment; filename="healthtrack_export_\d{8}\.(csv|json)"$')


def _ready_export(client, account, fmt: str = "csv"):
    created = new_export(client, account["header"], format=fmt,
                         password=account["password"])
    export_id = int(created["export_id"])
    return export_id, job_row(export_id)["file_token"]


# ════════════════════════════════════════════════════════════════════
# N —— 合法下载
# ════════════════════════════════════════════════════════════════════
def test_e03_download_csv_ok(client, exporter):
    """N：合法下载 → ``200`` **文件流** + 冻结响应头；内容与落盘文件逐字节一致。"""
    export_id, token = _ready_export(client, exporter, "csv")
    resp = download(client, exporter["header"], export_id, token)

    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert resp.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert DISPOSITION.match(resp.headers["Content-Disposition"]), resp.headers["Content-Disposition"]
    assert HEX32.match(resp.headers["X-Request-Id"])
    # 响应头**不得**出现服务器真实路径
    assert export_dir() not in str(dict(resp.headers))
    assert resp.get_data() == export_file_bytes(export_id)


def test_e03_download_json_content_type(client, exporter):
    """N：``json`` 导出下载的 ``Content-Type`` 为 ``application/json; charset=utf-8``。"""
    export_id, token = _ready_export(client, exporter, "json")
    resp = download(client, exporter["header"], export_id, token)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
    assert DISPOSITION.match(resp.headers["Content-Disposition"])
    assert resp.headers["Content-Disposition"].endswith('.json"')


def test_e03_first_download_records_timestamp(client, exporter):
    """幂等：首次下载写 ``downloaded_at`` 并把状态置 ``downloaded``。"""
    export_id, token = _ready_export(client, exporter)
    assert job_row(export_id)["downloaded_at"] is None

    assert download(client, exporter["header"], export_id, token).status_code == 200
    row = job_row(export_id)
    assert row["downloaded_at"] is not None
    assert row["status"] == "downloaded"


def test_e03_repeat_download_keeps_first_timestamp(client, exporter):
    """幂等：窗口内**可重复下载**，``downloaded_at`` **仅记首次**（不覆盖）。"""
    export_id, token = _ready_export(client, exporter)
    assert download(client, exporter["header"], export_id, token).status_code == 200
    first_at = job_row(export_id)["downloaded_at"]

    again = download(client, exporter["header"], export_id, token)
    assert again.status_code == 200
    assert again.get_data() == export_file_bytes(export_id)
    assert job_row(export_id)["downloaded_at"] == first_at


# ════════════════════════════════════════════════════════════════════
# O / P —— 非法凭证 / 越权
# ════════════════════════════════════════════════════════════════════
def test_e03_invalid_file_token(client, exporter):
    """O：``file_token`` 不匹配 / 缺失 → ``404 RESOURCE_NOT_FOUND``。"""
    export_id, token = _ready_export(client, exporter)
    wrong = "0" * 32 if token != "0" * 32 else "1" * 32

    resp = download(client, exporter["header"], export_id, wrong)
    assert resp.status_code == 404 and resp.get_json()["code"] == "RESOURCE_NOT_FOUND"

    missing = download(client, exporter["header"], export_id, None)
    assert missing.status_code == 404 and missing.get_json()["code"] == "RESOURCE_NOT_FOUND"


def test_e03_other_user_cannot_download(client, exporter, peer):
    """P：他人任务**三条件校验** —— 非本人 / 凭证不匹配均 → ``404``。"""
    export_id, token = _ready_export(client, exporter)

    by_peer = download(client, peer["header"], export_id, token)
    assert by_peer.status_code == 404 and by_peer.get_json()["code"] == "RESOURCE_NOT_FOUND"

    peer_id, peer_token = _ready_export(client, peer)
    cross = download(client, exporter["header"], peer_id, peer_token)
    assert cross.status_code == 404

    mismatched = download(client, peer["header"], peer_id, token)
    assert mismatched.status_code == 404
    # 越权失败**未**写入 ``downloaded_at``
    assert job_row(peer_id)["downloaded_at"] is None


def test_e03_not_found_task(client, exporter):
    """O：任务不存在 → ``404``。"""
    resp = download(client, exporter["header"], 987654321, "0" * 32)
    assert resp.status_code == 404 and resp.get_json()["code"] == "RESOURCE_NOT_FOUND"


# ════════════════════════════════════════════════════════════════════
# Q —— 窗口限制
# ════════════════════════════════════════════════════════════════════
def test_e03_download_expired(client, exporter):
    """Q：``download_expires_at`` 已过 → ``410 EXPORT_EXPIRED``。"""
    export_id, token = _ready_export(client, exporter)
    set_job_state(export_id, download_expires_at=dt_before(minutes=1))

    resp = download(client, exporter["header"], export_id, token)
    assert resp.status_code == 410
    assert resp.get_json()["code"] == "EXPORT_EXPIRED"
    assert job_row(export_id)["downloaded_at"] is None


def test_e03_download_purged(client, exporter):
    """Q：``purge_at`` 已过（``purged``）→ ``410 EXPORT_EXPIRED``。"""
    export_id, token = _ready_export(client, exporter)
    set_job_state(export_id, purge_at=dt_before(minutes=1),
                  download_expires_at=dt_before(minutes=2))

    resp = download(client, exporter["header"], export_id, token)
    assert resp.status_code == 410 and resp.get_json()["code"] == "EXPORT_EXPIRED"


def test_e03_download_missing_file(client, exporter):
    """Q：任务 ``ready`` 但磁盘文件缺失 → ``410``（**不静默**返回空文件）。"""
    export_id, token = _ready_export(client, exporter)
    # 模拟「文件已被强制清理」：把 ``file_path`` 指向 `EXPORT_DIR` 内**不存在**的路径
    set_job_state(export_id, file_path=os.path.join(export_dir(), "0" * 32 + ".csv"))

    resp = download(client, exporter["header"], export_id, token)
    assert resp.status_code == 410 and resp.get_json()["code"] == "EXPORT_EXPIRED"


# ════════════════════════════════════════════════════════════════════
# R —— 路径安全
# ════════════════════════════════════════════════════════════════════
def test_e03_path_traversal_is_rejected(client, exporter):
    """R：库内 ``file_path`` 不在 ``EXPORT_DIR`` 之内 → ``404``（**禁止读任意文件**）。"""
    export_id, token = _ready_export(client, exporter)
    # ★ OPEN-TI-1-B：``EXPORT_DIR`` 测试期已隔离到**系统临时目录**，
    #   旧的 ``export_dir()/../../app/...`` 相对回退无法再到达仓库。
    #   改为按本文件位置反推 ``backend/`` 根取「越界但真实存在」的同一目标文件
    #   （与 batch8 outside 构造同一思路）；**被测安全属性与全部断言不变**。
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outside = os.path.join(backend_root, "app", "services", "export_service.py")
    assert os.path.isfile(os.path.realpath(outside)), "构造用例失败：越界目标文件不存在"

    set_job_state(export_id, file_path=outside)
    resp = download(client, exporter["header"], export_id, token)
    assert resp.status_code == 404 and resp.get_json()["code"] == "RESOURCE_NOT_FOUND"
    assert b"def create_export" not in resp.get_data()


def test_e03_path_injection_via_token(client, exporter):
    """R：``file_token`` 传入路径形态（``../`` / 绝对路径）→ ``404``（无法命中任何任务）。"""
    export_id, _token = _ready_export(client, exporter)
    for evil in ("../../etc/passwd", "/etc/passwd", "..%2f..%2fapp"):
        resp = download(client, exporter["header"], export_id, evil)
        assert resp.status_code == 404, evil
        assert resp.get_json()["code"] == "RESOURCE_NOT_FOUND"


def test_e03_no_client_controllable_path_parameter(client, exporter):
    """R：**不存在**任何可由客户端指定服务器路径的参数（多余参数被忽略、不改变行为）。"""
    export_id, token = _ready_export(client, exporter)
    resp = client.get(
        f"/api/v1/exports/{export_id}/download?file_token={token}"
        "&file_path=/etc/passwd&path=../../app/services/export_service.py",
        headers=exporter["header"],
    )
    assert resp.status_code == 200
    assert resp.get_data() == export_file_bytes(export_id)
