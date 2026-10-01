# -*- coding: utf-8 -*-
"""S2 第三批 F（R-03 记录详情）。

覆盖验收项：F（详情）、J（越权 404）、M（软删不可见）、P/Q（响应契约）。
"""
from __future__ import annotations

from app.core.errors import ErrorCode
from app.services.record_service import RECORD_KEYS
from tests.batch3.conftest import API, created_record, post_record

WEIGHT = {"metric_type": "weight", "value_1": 72.5, "unit": None,
          "recorded_at": "2026-09-13 07:30:00"}


def _create(client, header, payload=None, **overrides):
    body = dict(payload or WEIGHT)
    body.update(overrides)
    body = {k: v for k, v in body.items() if v is not None}
    return created_record(post_record(client, header, body))


def _get(client, header, record_id):
    return client.get(f"{API}/records/{record_id}", headers=header)


def test_r03_returns_fixed_record_keys(client, user):
    """F：返回既定字段集合（未填写字段**保留键并返回 null**）。"""
    record = _create(client, user["header"])
    resp = _get(client, user["header"], record["id"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert sorted(body.keys()) == ["code", "data", "message", "request_id"]
    assert set(body["data"].keys()) == {"record", "derived"}
    assert set(body["data"]["record"].keys()) == set(RECORD_KEYS)
    assert body["data"]["record"]["value_2"] is None
    assert body["data"]["record"]["tags"] == []


def test_r03_derived_returned_and_not_persisted(client, ready_user):
    """F：详情同样返回 ``derived``；派生值**不落库**。"""
    record = _create(client, ready_user["header"], value_1=70.0)
    body = _get(client, ready_user["header"], record["id"]).get_json()["data"]
    assert body["derived"]["bmi"] == 22.9
    # 再次读取结果一致（说明是按需计算，不是写库）
    again = _get(client, ready_user["header"], record["id"]).get_json()["data"]
    assert again["derived"] == body["derived"]


def test_r03_tags_returned(client, user):
    """F：mood 标签随详情返回（保序）。"""
    record = _create(client, user["header"],
                     {"metric_type": "mood", "value_1": 4,
                      "tags": ["focused", "relaxed"], "recorded_at": "2026-09-13 21:00:00"})
    body = _get(client, user["header"], record["id"]).get_json()["data"]
    assert body["record"]["tags"] == ["focused", "relaxed"]


def test_r03_unknown_id_returns_404(client, user):
    """F/J：不存在的 id → 404。"""
    resp = _get(client, user["header"], 99999999)
    assert resp.status_code == 404
    assert resp.get_json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_r03_cross_user_returns_404_without_leaking(client, user, peer):
    """J：跨用户访问 → **统一 404**，不泄露资源归属与存在性。"""
    record = _create(client, peer["header"])
    own_missing = _get(client, user["header"], 99999998).get_json()
    cross = _get(client, user["header"], record["id"])
    assert cross.status_code == 404
    body = cross.get_json()
    assert body["code"] == own_missing["code"]
    assert body["message"] == own_missing["message"]      # 文案完全一致，无法区分
    assert body["data"] is None


def test_r03_soft_deleted_returns_404(client, user):
    """M：软删后详情不可见（404）。"""
    record = _create(client, user["header"])
    assert client.delete(f"{API}/records/{record['id']}",
                         headers=user["header"]).status_code == 200
    assert _get(client, user["header"], record["id"]).status_code == 404


def test_r03_requires_auth(client, user):
    """L：R-03 必须认证。"""
    record = _create(client, user["header"])
    assert client.get(f"{API}/records/{record['id']}").status_code == 401


def test_r03_non_integer_id_not_matched(client, user):
    """F：路径参数为整数型（非整数不落入该路由）。"""
    assert client.get(f"{API}/records/abc", headers=user["header"]).status_code == 404
