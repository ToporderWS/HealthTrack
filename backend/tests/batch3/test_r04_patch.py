# -*- coding: utf-8 -*-
"""S2 第三批 G（R-04 修改记录）。

覆盖验收项：G（局部更新 / 标签整体替换 / 禁止字段）、J（越权 404）、
M（软删不可编辑）、B（软提示同样适用于编辑）。
"""
from __future__ import annotations

from app.core.errors import ErrorCode
from app.core.warnings import WarningCode
from tests.batch3.conftest import API, created_record, post_record

WEIGHT = {"metric_type": "weight", "value_1": 72.5, "recorded_at": "2026-09-13 07:30:00"}
MOOD = {"metric_type": "mood", "value_1": 4, "tags": ["focused", "relaxed"],
        "recorded_at": "2026-09-13 21:00:00"}


def _create(client, header, payload):
    return created_record(post_record(client, header, payload))


def _patch(client, header, record_id, body):
    return client.patch(f"{API}/records/{record_id}", headers=header, json=body)


def _detail(client, header, record_id):
    return client.get(f"{API}/records/{record_id}", headers=header).get_json()["data"]["record"]


def test_r04_partial_update_keeps_untouched_fields(client, user):
    """G：局部更新（仅改 value_1，其余字段保持）。"""
    record = _create(client, user["header"], WEIGHT)
    resp = _patch(client, user["header"], record["id"], {"value_1": 71.0})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["data"]
    assert body["record"]["value_1"] == 71.0
    assert body["record"]["recorded_at"] == "2026-09-13 07:30:00"
    assert body["record"]["metric_type"] == "weight"
    assert body["record"]["unit"] == "kg"


def test_r04_response_shape(client, user):
    """P/Q：编辑成功 → 200 + 四键 + ``{record, derived, warnings}``。"""
    record = _create(client, user["header"], WEIGHT)
    resp = _patch(client, user["header"], record["id"], {"note": "备注"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert sorted(body.keys()) == ["code", "data", "message", "request_id"]
    assert set(body["data"].keys()) == {"record", "derived", "warnings"}
    assert resp.headers["X-Request-Id"] == body["request_id"]


def test_r04_metric_type_cannot_be_modified_even_if_identical(client, user):
    """G：``metric_type`` **一旦出现（即使值相同）→ 422**。"""
    record = _create(client, user["header"], WEIGHT)
    for value in ("weight", "bp"):
        resp = _patch(client, user["header"], record["id"], {"metric_type": value})
        assert resp.status_code == 422, (value, resp.get_json())
        assert resp.get_json()["code"] == ErrorCode.VALIDATION_FAILED
    assert _detail(client, user["header"], record["id"])["metric_type"] == "weight"


def test_r04_forbidden_field_for_metric_rejected(client, user):
    """G：编辑同样执行「禁止字段」判定（weight 携带 value_2 → 422）。"""
    record = _create(client, user["header"], WEIGHT)
    assert _patch(client, user["header"], record["id"], {"value_2": 10}).status_code == 422
    assert _patch(client, user["header"], record["id"],
                  {"tags": ["tired"]}).status_code == 422


def test_r04_tags_whole_replacement(client, user):
    """G：标签**整体替换**（移除的物理删除、新增的插入）。

    注：``record_tag`` 无排序列（0 migration），返回顺序按 ``record_tag.id``（插入序），
    冻结契约**未规定**标签顺序，故按集合断言。
    """
    record = _create(client, user["header"], MOOD)
    assert set(_detail(client, user["header"], record["id"])["tags"]) == {"focused", "relaxed"}

    resp = _patch(client, user["header"], record["id"], {"tags": ["tired", "focused"]})
    assert resp.status_code == 200, resp.get_json()
    assert set(resp.get_json()["data"]["record"]["tags"]) == {"tired", "focused"}
    assert set(_detail(client, user["header"], record["id"])["tags"]) == {"tired", "focused"}

    # 清空标签
    resp = _patch(client, user["header"], record["id"], {"tags": []})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["record"]["tags"] == []
    assert _detail(client, user["header"], record["id"])["tags"] == []


def test_r04_tag_rows_replaced_in_database(client, user):
    """G：被移除的 ``record_tag`` 行**物理删除**（S1-B 数据库 §9.2），不产生孤儿。"""
    from sqlalchemy import func, select

    from app.core.db import get_session_factory
    from app.models.record_tag import RecordTag

    record = _create(client, user["header"], MOOD)
    _patch(client, user["header"], record["id"], {"tags": ["low"]})

    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(RecordTag.tag_value, RecordTag.is_deleted).where(
                RecordTag.record_id == record["id"]
            )
        ).all()
        total = db.execute(
            select(func.count(RecordTag.id)).where(RecordTag.record_id == record["id"])
        ).scalar()
    assert total == 1                                   # focused / relaxed 已物理删除
    assert [r[0] for r in rows] == ["low"]


def test_r04_invalid_tag_value_rejected(client, user):
    """G：标签取值受控（非法 → 422）。"""
    record = _create(client, user["header"], MOOD)
    assert _patch(client, user["header"], record["id"],
                  {"tags": ["not_a_tag"]}).status_code == 422


def test_r04_soft_warning_then_ack(client, user):
    """B：编辑同样遵循软提示契约（200 不写入 → 确认后写入）。"""
    record = _create(client, user["header"], WEIGHT)

    resp = _patch(client, user["header"], record["id"], {"value_1": 320})
    body = resp.get_json()
    assert resp.status_code == 200 and body["code"] == ErrorCode.SOFT_WARNING
    assert body["data"]["warnings"][0]["code"] == WarningCode.OUT_OF_COMMON_RANGE
    assert _detail(client, user["header"], record["id"])["value_1"] == 72.5   # 未写入

    resp = _patch(client, user["header"], record["id"],
                  {"value_1": 320, "acknowledge_warnings": True})
    assert resp.status_code == 200 and resp.get_json()["code"] == "OK"
    assert _detail(client, user["header"], record["id"])["value_1"] == 320


def test_r04_hard_block_on_edit(client, user):
    """G：编辑时的硬拦截（不可能值 → 422 且不落库）。"""
    record = _create(client, user["header"], WEIGHT)
    assert _patch(client, user["header"], record["id"], {"value_1": 5000}).status_code == 422
    assert _detail(client, user["header"], record["id"])["value_1"] == 72.5


def test_r04_unit_mismatch_rejected(client, user):
    """G：单位由服务端决定，客户端传入不一致 → 422。"""
    record = _create(client, user["header"], WEIGHT)
    assert _patch(client, user["header"], record["id"], {"unit": "lb"}).status_code == 422
    assert _patch(client, user["header"], record["id"], {"unit": "kg"}).status_code == 200


def test_r04_cross_user_returns_404(client, user, peer):
    """J：跨用户编辑 → 统一 404；他人数据不被改动。"""
    record = _create(client, peer["header"], WEIGHT)
    resp = _patch(client, user["header"], record["id"], {"value_1": 1.0})
    assert resp.status_code == 404
    assert resp.get_json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert _detail(client, peer["header"], record["id"])["value_1"] == 72.5


def test_r04_soft_deleted_not_editable(client, user):
    """M：软删记录不可编辑（404）。"""
    record = _create(client, user["header"], WEIGHT)
    client.delete(f"{API}/records/{record['id']}", headers=user["header"])
    assert _patch(client, user["header"], record["id"], {"value_1": 71.0}).status_code == 404


def test_r04_unknown_id_returns_404(client, user):
    """G：不存在 id → 404。"""
    assert _patch(client, user["header"], 99999999, {"value_1": 71.0}).status_code == 404


def test_r04_requires_auth(client, user):
    """L：R-04 必须认证。"""
    record = _create(client, user["header"], WEIGHT)
    assert client.patch(f"{API}/records/{record['id']}", json={"value_1": 71.0}).status_code == 401
