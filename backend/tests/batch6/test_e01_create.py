# -*- coding: utf-8 -*-
"""S2 第六批 E-01（``POST /api/v1/exports``）验收用例。

覆盖：A 正常创建 / B 未登录 401 / C 密码错误与失败次数 / D 验密成功计数清零 /
E 用户隔离 / F 软删除不进入导出 / G 敏感内部字段不泄露 / H 空数据导出 /
I 多类型健康记录导出 / Y Decimal 与时间格式稳定 / 参数校验 / 幂等。

> 约定：``new_export`` 返回**成功载荷 ``data``**（断言 202）；需要检查失败分支时
> 直接用 ``post_export`` 取**原始应答**。
"""
from __future__ import annotations

import csv
import io
import json
import re

from tests.batch6.conftest import (
    API,
    add_record,
    body_of,
    business_row_counts,
    day_before,
    export_dir,
    export_fail_count,
    export_file_bytes,
    export_filenames,
    job_row,
    new_export,
    post_export,
    set_job_state,
    ts_before,
)

DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
CREATE_KEYS = {
    "export_id", "format", "status", "record_count",
    "download_expires_at", "purge_at", "created_at",
}
EXPORT_COLUMNS = [
    "metric_type", "value_1", "value_2", "value_3", "unit",
    "attr_1", "attr_2", "recorded_at", "time_start", "note", "tags", "created_at",
]


def _rows(content: bytes):
    return list(csv.reader(io.StringIO(content.decode("utf-8"))))


# ════════════════════════════════════════════════════════════════════
# A —— 正常创建
# ════════════════════════════════════════════════════════════════════
def test_e01_create_ok_structure(client, exporter):
    """A：正常创建 —— ``202`` + 冻结字段 + **同步生成后真实最终状态即 ``ready``**。"""
    resp = post_export(client, exporter["header"], format="csv",
                       password=exporter["password"])
    assert resp.status_code == 202, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "导出任务已创建"
    data = body["data"]
    assert set(data.keys()) == CREATE_KEYS, data
    assert isinstance(data["export_id"], int) and data["export_id"] > 0
    assert data["format"] == "csv"
    assert data["status"] == "ready"          # S1-D §5.3：同步生成 → 真实最终状态
    assert data["record_count"] == 3
    assert DATETIME_RE.match(data["download_expires_at"])
    assert DATETIME_RE.match(data["purge_at"])
    assert DATETIME_RE.match(data["created_at"])
    # TTL / purge 窗口 = 10 / 60 分钟
    row = job_row(int(data["export_id"]))
    assert (row["download_expires_at"] - row["created_at"]).total_seconds() == 600
    assert (row["purge_at"] - row["created_at"]).total_seconds() == 3600
    assert row["downloaded_at"] is None


def test_e01_response_has_no_file_path_or_token(client, exporter):
    """G：E-01 响应**永不返回** ``file_path``；创建阶段也**不返回** ``file_token``。"""
    resp = post_export(client, exporter["header"], format="csv",
                       password=exporter["password"])
    data = resp.get_json()["data"]
    assert "file_path" not in data and "file_token" not in data
    assert "file_path" not in resp.get_data(as_text=True)


def test_e01_writes_file_under_export_dir(client, exporter):
    """A：任务落盘于 ``EXPORT_DIR``，且 ``file_size_bytes`` 与真实文件一致。"""
    data = new_export(client, exporter["header"], format="csv",
                      password=exporter["password"])
    row = job_row(int(data["export_id"]))
    path = row["file_path"]
    assert path and path.startswith(export_dir()), path
    content = export_file_bytes(int(data["export_id"]))
    assert len(content) == row["file_size_bytes"]
    assert len(content) > 0
    assert any(name.endswith(".csv") for name in export_filenames())


def test_e01_job_row_is_bound_to_token_user(client, exporter):
    """E：任务行 ``user_id`` = Access Token 用户（**不接受客户端注入**）。"""
    data = new_export(client, exporter["header"], format="csv",
                      password=exporter["password"])
    row = job_row(int(data["export_id"]))
    assert row["user_id"] == exporter["user_id"]
    assert row["metric_types"] is None        # 未指定 = 全部指标
    assert len(row["file_token"]) == 32        # CHAR(32) 下载凭证


# ════════════════════════════════════════════════════════════════════
# H —— 空数据导出
# ════════════════════════════════════════════════════════════════════
def test_e01_empty_dataset(client, user):
    """H：无数据导出 → ``202``、``record_count = 0``、文件仅表头（**不静默失败**）。"""
    data = new_export(client, user["header"], format="csv", password=user["password"])
    assert data["record_count"] == 0
    assert data["status"] == "ready"
    rows = _rows(export_file_bytes(int(data["export_id"])))
    assert rows == [EXPORT_COLUMNS]


# ════════════════════════════════════════════════════════════════════
# I / G —— 多类型导出 + 敏感字段不泄露
# ════════════════════════════════════════════════════════════════════
def test_e01_csv_header_excludes_internal_fields(client, exporter):
    """G：CSV 表头 = 冻结事实字段；**不含 ``id`` / ``user_id`` / Token / 内部标识**。"""
    data = new_export(client, exporter["header"], format="csv",
                      password=exporter["password"])
    header = _rows(export_file_bytes(int(data["export_id"])))[0]
    assert header == EXPORT_COLUMNS
    assert "id" not in header and "user_id" not in header
    assert "file_token" not in header and "token" not in header


def test_e01_multi_metric_rows_exported(client, exporter):
    """I：多类型健康记录全部导出，且**不含**任何用户的内部主键值。"""
    data = new_export(client, exporter["header"], format="csv",
                      password=exporter["password"])
    rows = _rows(export_file_bytes(int(data["export_id"])))
    assert len(rows) == 1 + 3
    kinds = [r[0] for r in rows[1:]]
    assert sorted(kinds) == ["mood", "water", "weight"]
    assert rows[1:] == sorted(rows[1:], key=lambda r: r[7])   # recorded_at 升序
    assert all(str(exporter["user_id"]) not in r for r in rows[1:])


def test_e01_json_format_export(client, exporter):
    """I：``format=json`` 导出为 JSON（顶层 ``records``，元素字段 = 冻结列）。"""
    data = new_export(client, exporter["header"], format="json",
                      password=exporter["password"])
    assert data["format"] == "json"
    payload = json.loads(export_file_bytes(int(data["export_id"])).decode("utf-8"))
    assert list(payload.keys()) == ["records"]
    assert len(payload["records"]) == 3
    for item in payload["records"]:
        assert list(item.keys()) == EXPORT_COLUMNS
        assert "id" not in item and "user_id" not in item


def test_e01_mood_tags_exported(client, exporter):
    """I：``mood`` 标签随行导出（仅未软删标签）。"""
    data = new_export(client, exporter["header"], format="csv", metric_types=["mood"],
                      password=exporter["password"])
    rows = _rows(export_file_bytes(int(data["export_id"])))
    assert len(rows) == 2
    assert rows[1][0] == "mood"
    assert rows[1][10] == "relaxed|focused"
    assert DATETIME_RE.match(rows[1][11])


# ════════════════════════════════════════════════════════════════════
# F —— 软删除数据不进入导出
# ════════════════════════════════════════════════════════════════════
def test_e01_soft_deleted_records_excluded(client, exporter):
    """F：软删记录**不进导出**（含其标签）。"""
    created = add_record(client, exporter["header"], metric_type="water", value_1=999,
                         recorded_at=ts_before(days=1), note="软删目标")
    record_id = int(created["record"]["id"])
    assert client.delete(f"{API}/records/{record_id}",
                         headers=exporter["header"]).status_code == 200

    data = new_export(client, exporter["header"], format="csv",
                      password=exporter["password"])
    assert data["record_count"] == 3          # 999 那条被软删，不计入
    content = export_file_bytes(int(data["export_id"])).decode("utf-8")
    assert "软删目标" not in content
    assert "999" not in content


# ════════════════════════════════════════════════════════════════════
# Y —— 数值 / 时间格式稳定
# ════════════════════════════════════════════════════════════════════
def test_e01_decimal_and_datetime_format_stable(client, exporter):
    """Y：Decimal 归一（``70.50`` → ``70.5``；整数值保持整数）+ 时间格式固定。"""
    data = new_export(client, exporter["header"], format="csv",
                      metric_types=["weight", "water"], password=exporter["password"])
    rows = _rows(export_file_bytes(int(data["export_id"])))
    by_metric = {r[0]: r for r in rows[1:]}
    assert by_metric["weight"][1] == "70.5"           # 70.50 归一，无多余尾零
    assert by_metric["weight"][4] == "kg"
    assert by_metric["weight"][8] == ""               # time_start 非睡眠恒为空
    assert by_metric["water"][1] == "500"             # 整数值不带小数
    assert by_metric["water"][4] == "ml"
    assert DATETIME_RE.match(by_metric["weight"][7])
    assert DATETIME_RE.match(by_metric["weight"][11])


def test_e01_json_decimal_is_numeric_type(client, exporter):
    """Y：JSON 导出中数值为**数值类型**（整数 ``int`` / 小数 ``float``），空值为 ``null``。"""
    data = new_export(client, exporter["header"], format="json",
                      metric_types=["weight", "water"], password=exporter["password"])
    records = json.loads(export_file_bytes(int(data["export_id"])).decode("utf-8"))["records"]
    by_metric = {r["metric_type"]: r for r in records}
    assert by_metric["weight"]["value_1"] == 70.5
    assert isinstance(by_metric["weight"]["value_1"], float)
    assert by_metric["water"]["value_1"] == 500
    assert isinstance(by_metric["water"]["value_1"], int)
    assert by_metric["weight"]["value_2"] is None
    assert by_metric["weight"]["tags"] == []


# ════════════════════════════════════════════════════════════════════
# 参数校验 / 二次验密 / 进行中冲突
# ════════════════════════════════════════════════════════════════════
def test_e01_invalid_format(client, user):
    """参数：``format`` 非法 / 缺失 → ``400 INVALID_PARAM``。"""
    bad = post_export(client, user["header"], format="xml", password=user["password"])
    assert bad.status_code == 400 and bad.get_json()["code"] == "INVALID_PARAM"

    missing = post_export(client, user["header"], password=user["password"])
    body = body_of(missing, 400)
    assert any(e["field"] == "format" for e in body["errors"])


def test_e01_invalid_metric_types(client, user):
    """参数：``metric_types`` 非法值 / 空数组 / 非数组 → ``400 INVALID_PARAM``。"""
    for raw in (["unknown"], [], "weight"):
        resp = post_export(client, user["header"], format="csv", metric_types=raw,
                           password=user["password"])
        assert resp.status_code == 400, (raw, resp.get_json())
        assert resp.get_json()["code"] == "INVALID_PARAM"


def test_e01_range_bound_validation(client, user):
    """参数：``range_start >= range_end`` → ``400``；非法日期 → ``400``。"""
    resp = post_export(client, user["header"], format="csv",
                       range_start="2026-03-02", range_end="2026-03-01",
                       password=user["password"])
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"

    resp2 = post_export(client, user["header"], format="csv", range_end="2026/03/01",
                        password=user["password"])
    assert resp2.status_code == 400 and resp2.get_json()["code"] == "INVALID_PARAM"


def test_e01_range_is_half_open(client, exporter):
    """参数：时间范围为**半开区间** ``[range_start, range_end)``。"""
    data = new_export(client, exporter["header"], format="csv",
                      range_start=day_before(1), range_end=day_before(0),
                      password=exporter["password"])
    assert data["record_count"] == 2                       # 昨日 water + mood；不含前日 weight
    rows = _rows(export_file_bytes(int(data["export_id"])))
    assert sorted(r[0] for r in rows[1:]) == ["mood", "water"]


def test_e01_password_wrong_then_session_aborted(client, user):
    """C：密码错误 → ``422 PASSWORD_INVALID`` 且计数 +1；连错 3 次 → ``429``。"""
    for expected_count in (1, 2):
        resp = post_export(client, user["header"], format="csv", password="wrong1234")
        assert resp.status_code == 422, resp.get_json()
        assert resp.get_json()["code"] == "PASSWORD_INVALID"
        assert export_fail_count(user["user_id"]) == expected_count

    resp = post_export(client, user["header"], format="csv", password="wrong1234")
    assert resp.status_code == 429
    assert resp.get_json()["code"] == "SESSION_VERIFY_ABORTED"
    assert export_fail_count(user["user_id"]) == 3
    # 中止后**未创建任何任务**（计数只存会话，不落任务表）
    assert business_row_counts()["export_job"] == 0


def test_e01_no_job_created_when_password_wrong(client, user):
    """C：验密失败**不产生** ``export_job`` 记录，也不落盘文件。"""
    before = export_filenames()
    for _ in range(3):
        post_export(client, user["header"], format="csv", password="wrong1234")
    assert business_row_counts()["export_job"] == 0
    assert export_filenames() == before


def test_e01_password_success_resets_counter(client, user):
    """D：验密成功后 ``export_pwd_fail_count`` **清零**。"""
    post_export(client, user["header"], format="csv", password="wrong1234")
    post_export(client, user["header"], format="csv", password="wrong1234")
    assert export_fail_count(user["user_id"]) == 2

    data = new_export(client, user["header"], format="csv", password=user["password"])
    assert data["status"] == "ready"
    assert export_fail_count(user["user_id"]) == 0


def test_e01_in_progress_conflict(client, exporter):
    """冲突：已有 ``ready`` 任务 → ``409 EXPORT_IN_PROGRESS``；窗口过后可再导出。"""
    first = new_export(client, exporter["header"], format="csv",
                       password=exporter["password"])
    conflict = post_export(client, exporter["header"], format="csv",
                           password=exporter["password"])
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "EXPORT_IN_PROGRESS"

    # 已下载（downloaded）→ 不再阻塞
    set_job_state(int(first["export_id"]), status="downloaded")
    third = new_export(client, exporter["header"], format="csv",
                       password=exporter["password"])
    assert third["status"] == "ready"


def test_e01_idempotency_key_replays_first_result(client, exporter):
    """幂等：同 ``Idempotency-Key`` + 同请求体 → 回放首次结果（**不重复生成文件**）。"""
    body = {"format": "csv", "password": exporter["password"]}
    headers = dict(exporter["header"])
    headers["Idempotency-Key"] = "edge-b6-idem-0001"

    first = client.post(f"{API}/exports", headers=headers, json=body)
    assert first.status_code == 202, first.get_json()
    second = client.post(f"{API}/exports", headers=headers, json=body)
    assert second.status_code == 202, second.get_json()
    assert second.get_json()["data"]["export_id"] == first.get_json()["data"]["export_id"]
    assert business_row_counts()["export_job"] == 1


def test_e01_rejects_client_user_id(client, user):
    """隔离：请求体携带 ``user_id`` → 全局守卫 ``400 INVALID_PARAM``。"""
    resp = client.post(f"{API}/exports", headers=user["header"],
                       json={"format": "csv", "password": user["password"], "user_id": 1})
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"
