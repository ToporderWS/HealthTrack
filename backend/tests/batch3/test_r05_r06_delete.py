# -*- coding: utf-8 -*-
"""S2 第三批 H/I/K（R-05 单条删除 + R-06 批量删除）。

覆盖验收项：
- H：R-05 软删（不物理删除 / 标签同步软删）
- I：R-06 批量删除（密码验证 / 服务端 COUNT / COUNT_MISMATCH / 二次确认 / 幂等）
- J：跨用户 404 与零影响
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import get_session_factory
from app.core.errors import ErrorCode
from app.models.record_tag import RecordTag
from app.services import record_service
from tests.batch3.conftest import API, created_record, post_record

BASE = datetime(2026, 8, 1, 8, 0, 0)
MOOD = {"metric_type": "mood", "value_1": 4, "tags": ["tired", "low"],
        "recorded_at": "2026-09-13 21:00:00"}


def _create(client, header, payload):
    return created_record(post_record(client, header, payload))


def _count(client, header):
    return client.get(f"{API}/records/count", headers=header).get_json()["data"]["count"]


def _seed_water(client, header, count: int, *, start: int = 0):
    for i in range(count):
        at = (BASE + timedelta(minutes=start + i)).strftime("%Y-%m-%d %H:%M:%S")
        post_record(client, header, {"metric_type": "water", "value_1": 200, "recorded_at": at})


def _batch(client, header, body):
    return client.post(f"{API}/records/batch-delete", headers=header, json=body)


# ════════════════════════════════════════════════════════════════════
# R-05 单条删除
# ════════════════════════════════════════════════════════════════════
def test_r05_soft_delete_returns_deleted_count(client, user):
    """H：删除成功 → ``{"deleted_count": 1}``，记录不可见但**行仍在**。"""
    record = _create(client, user["header"], MOOD)
    resp = client.delete(f"{API}/records/{record['id']}", headers=user["header"])
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"] == {"deleted_count": 1}
    assert client.get(f"{API}/records/{record['id']}",
                      headers=user["header"]).status_code == 404
    assert _count(client, user["header"]) == 0

    from app.models.health_record import HealthRecord

    factory = get_session_factory()
    with factory() as db:
        row = db.execute(select(HealthRecord).where(HealthRecord.id == record["id"])).scalars().first()
    assert row is not None and int(row.is_deleted) == 1     # **不是物理删除**
    assert row.deleted_at is not None


def test_r05_tags_soft_deleted_with_parent(client, user):
    """H：标签**随父记录同步软删**（保留行，不物理删除）。"""
    record = _create(client, user["header"], MOOD)
    client.delete(f"{API}/records/{record['id']}", headers=user["header"])

    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            select(RecordTag.tag_value, RecordTag.is_deleted).where(
                RecordTag.record_id == record["id"]
            )
        ).all()
    assert len(rows) == 2
    assert all(int(r[1]) == 1 for r in rows)


def test_r05_repeat_delete_returns_404(client, user):
    """H：重复删除 → 404（幂等语义由前端承担，服务端如实返回）。"""
    record = _create(client, user["header"], MOOD)
    assert client.delete(f"{API}/records/{record['id']}",
                         headers=user["header"]).status_code == 200
    assert client.delete(f"{API}/records/{record['id']}",
                         headers=user["header"]).status_code == 404


def test_r05_cross_user_returns_404_and_no_effect(client, user, peer):
    """J：跨用户删除 → 404，且**他人数据零影响**。"""
    record = _create(client, peer["header"], MOOD)
    resp = client.delete(f"{API}/records/{record['id']}", headers=user["header"])
    assert resp.status_code == 404
    assert resp.get_json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert client.get(f"{API}/records/{record['id']}",
                      headers=peer["header"]).status_code == 200
    assert _count(client, peer["header"]) == 1


def test_r05_unknown_id_returns_404(client, user):
    """H：不存在 id → 404。"""
    assert client.delete(f"{API}/records/99999999", headers=user["header"]).status_code == 404


def test_r05_requires_auth(client, user):
    """L：R-05 必须认证。"""
    record = _create(client, user["header"], MOOD)
    assert client.delete(f"{API}/records/{record['id']}").status_code == 401


# ════════════════════════════════════════════════════════════════════
# R-06 批量删除
# ════════════════════════════════════════════════════════════════════
def test_r06_password_required_and_verified(client, user):
    """I：必须密码验证；缺失 → 400；错误 → 422 ``PASSWORD_INVALID``。"""
    _seed_water(client, user["header"], 3)
    assert _batch(client, user["header"], {}).status_code == 400          # 缺失 → 400 INVALID_PARAM
    resp = _batch(client, user["header"], {"password": "wrong-pass-1"})
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["code"] == ErrorCode.PASSWORD_INVALID
    assert _count(client, user["header"]) == 3          # 未删除


def test_r06_password_failure_does_not_touch_login_lockout(client, user):
    """I：批量删除的密码失败**不纳入登录锁定计数**（LOCK 表不新增本用户行）。"""
    from app.models.login_failure_state import LoginFailureState

    _seed_water(client, user["header"], 1)
    for _ in range(4):
        _batch(client, user["header"], {"password": "wrong-pass-1"})

    factory = get_session_factory()
    with factory() as db:
        row = db.execute(
            select(LoginFailureState).where(LoginFailureState.username == user["username"])
        ).scalars().first()
    assert row is None
    # 账号仍可正常登录
    assert client.post(f"{API}/auth/login", json={
        "username": user["username"], "password": user["password"],
    }).status_code in (200, 201)


def test_r06_deletes_by_metric_and_range(client, user):
    """I：按指标 + 时间范围批量软删，返回实际删除条数。"""
    _seed_water(client, user["header"], 4)                                  # 08:00~08:03
    post_record(client, user["header"],
                {"metric_type": "weight", "value_1": 70.0, "recorded_at": "2026-08-01 08:00:00"})

    resp = _batch(client, user["header"], {
        "metric_type": "water", "password": user["password"],
        "start": "2026-08-01 08:00:00", "end": "2026-08-01 08:02:00",
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"] == {"deleted_count": 2}
    assert _count(client, user["header"]) == 3                              # 2 water + 1 weight


def test_r06_count_mismatch_returns_409(client, user):
    """I：``expected_count`` 与服务端实际不一致 → 409 ``COUNT_MISMATCH``（不删除）。"""
    _seed_water(client, user["header"], 3)
    resp = _batch(client, user["header"], {
        "metric_type": "water", "password": user["password"], "expected_count": 5,
    })
    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert body["code"] == ErrorCode.COUNT_MISMATCH
    assert body["data"] == {"expected_count": 5, "actual_count": 3}
    assert _count(client, user["header"]) == 3


def test_r06_matching_expected_count_succeeds(client, user):
    """I：``expected_count`` 一致 → 正常删除（服务端 COUNT 为准）。"""
    _seed_water(client, user["header"], 3)
    resp = _batch(client, user["header"], {
        "metric_type": "water", "password": user["password"], "expected_count": 3,
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"] == {"deleted_count": 3}


def test_r06_large_batch_requires_confirm_text(client, user, monkeypatch):
    """I：条数达到阈值需 ``confirm_text = "确认删除"``，否则 422。"""
    monkeypatch.setattr(record_service, "CONFIRM_THRESHOLD", 3)
    _seed_water(client, user["header"], 4)

    resp = _batch(client, user["header"], {"metric_type": "water", "password": user["password"]})
    assert resp.status_code == 422, resp.get_json()
    assert _count(client, user["header"]) == 4

    resp = _batch(client, user["header"], {
        "metric_type": "water", "password": user["password"], "confirm_text": "删除",
    })
    assert resp.status_code == 422, resp.get_json()

    resp = _batch(client, user["header"], {
        "metric_type": "water", "password": user["password"], "confirm_text": "确认删除",
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"] == {"deleted_count": 4}
    assert _count(client, user["header"]) == 0


def test_r06_zero_match_returns_zero(client, user):
    """I：无匹配 → ``deleted_count = 0``（不报错）。"""
    _seed_water(client, user["header"], 2, start=100)
    resp = _batch(client, user["header"], {
        "metric_type": "water", "password": user["password"],
        "start": "2026-08-01 08:00:00", "end": "2026-08-01 08:01:00",
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"] == {"deleted_count": 0}


def test_r06_only_own_data_deleted(client, user, peer):
    """J：只删除本人数据（他人同条件数据零影响）。"""
    _seed_water(client, user["header"], 3)
    _seed_water(client, peer["header"], 5, start=300)

    resp = _batch(client, user["header"], {"metric_type": "water", "password": user["password"]})
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"deleted_count": 3}
    assert _count(client, peer["header"]) == 5


def test_r06_tags_soft_deleted_with_parents(client, user):
    """I：批量删除时标签同步软删。"""
    for i in range(2):
        post_record(client, user["header"], {
            "metric_type": "mood", "value_1": 3, "tags": ["tired"],
            "recorded_at": f"2026-08-01 08:0{i}:00",
        })
    resp = _batch(client, user["header"], {"metric_type": "mood", "password": user["password"]})
    assert resp.status_code == 200 and resp.get_json()["data"] == {"deleted_count": 2}

    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(select(RecordTag.is_deleted)).scalars().all()
    assert rows and all(int(x) == 1 for x in rows)


def test_r06_idempotency_key_replay(client, user):
    """I/O：批量删除同样支持 ``Idempotency-Key`` 重放（不重复执行）。"""
    _seed_water(client, user["header"], 2)
    body = {"metric_type": "water", "password": user["password"]}
    headers = dict(user["header"])
    headers["Idempotency-Key"] = "b3-batch-idem-0001"

    first = client.post(f"{API}/records/batch-delete", headers=headers, json=body)
    second = client.post(f"{API}/records/batch-delete", headers=headers, json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.get_json()["data"] == {"deleted_count": 2}
    assert second.get_json()["data"] == {"deleted_count": 2}
    assert _count(client, user["header"]) == 0


def test_r06_requires_auth(client):
    """L：R-06 必须认证。"""
    assert client.post(f"{API}/records/batch-delete", json={"password": "x"}).status_code == 401


def test_r06_idempotency_conflict_on_different_body(client, user):
    """I：同 key 不同体 → 409 ``IDEMPOTENCY_CONFLICT``。"""
    _seed_water(client, user["header"], 2)
    headers = dict(user["header"])
    headers["Idempotency-Key"] = "b3-batch-idem-0002"

    first = client.post(f"{API}/records/batch-delete", headers=headers,
                        json={"metric_type": "water", "password": user["password"]})
    assert first.status_code == 200
    second = client.post(f"{API}/records/batch-delete", headers=headers,
                         json={"metric_type": "mood", "password": user["password"]})
    assert second.status_code == 409
    assert second.get_json()["code"] == ErrorCode.IDEMPOTENCY_CONFLICT
