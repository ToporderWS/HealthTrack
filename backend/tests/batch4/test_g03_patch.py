# -*- coding: utf-8 -*-
"""S2 第四批 —— G-03 修改目标。

覆盖：更新成功 / ``goal_type`` 出现即 422 / ``start_weight_kg`` 不可修改 /
字段禁传 / 软删 → 404 / 跨用户 → 404 / 软提示 / ``user_id`` 注入 / 未认证。
"""
from __future__ import annotations

from tests.batch4.conftest import API, create_goal, created_goal, goal_row


def _patch(client, header, goal_id, **payload):
    return client.patch(f"{API}/goals/{goal_id}", headers=header, json=payload)


def test_g03_update_target_value(client, user):
    """G-03：更新 ``target_value`` → 200 + 回读一致。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    resp = _patch(client, user["header"], goal["id"], target_value=2500)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK" and body["message"] == "已保存"
    assert body["data"]["goal"]["target_value"] == 2500
    assert goal_row(goal["id"])["target_value"] == 2500

    items = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    assert items[0]["target_value"] == 2500


def test_g03_goal_type_immutable_even_if_same(client, user):
    """G-03：请求体出现 ``goal_type``（**即使值相同**）→ 422。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    resp = _patch(client, user["header"], goal["id"], goal_type="water", target_value=2100)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert any(e["field"] == "goal_type" for e in body["errors"])
    # 未被改动
    assert goal_row(goal["id"])["target_value"] == 2000


def test_g03_start_weight_kg_immutable(client, user):
    """G-03：``start_weight_kg`` 出现即 422（起始快照一经创建即冻结）。"""
    goal = created_goal(create_goal(client, user["header"], goal_type="weight",
                                    target_value=68.0, start_weight_kg=72.5))
    resp = _patch(client, user["header"], goal["id"], start_weight_kg=70.0)
    assert resp.status_code == 422
    assert any(e["field"] == "start_weight_kg" for e in resp.get_json()["errors"])
    assert float(goal_row(goal["id"])["start_weight_kg"]) == 72.5


def test_g03_field_restrictions(client, user):
    """G-03：非 sport 传 ``attr_1`` / 非 weight 传 ``target_date`` → 422。"""
    water = created_goal(create_goal(client, user["header"],
                                     goal_type="water", target_value=2000))
    bad_attr = _patch(client, user["header"], water["id"], attr_1="count")
    assert bad_attr.status_code == 422
    assert any(e["field"] == "attr_1" for e in bad_attr.get_json()["errors"])

    bad_date = _patch(client, user["header"], water["id"], target_date="2026-12-31")
    assert bad_date.status_code == 422
    assert any(e["field"] == "target_date" for e in bad_date.get_json()["errors"])


def test_g03_sport_attr_change_updates_unit(client, user):
    """G-03：``sport`` 改 ``attr_1`` → ``unit`` 随服务端规则同步。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="sport", target_value=150, attr_1="min"))
    resp = _patch(client, user["header"], goal["id"], attr_1="count", target_value=3)
    assert resp.status_code == 200, resp.get_json()
    updated = resp.get_json()["data"]["goal"]
    assert updated["attr_1"] == "count" and updated["unit"] == "count"
    assert goal_row(goal["id"])["unit"] == "count"

    invalid = _patch(client, user["header"], goal["id"], attr_1="times")
    assert invalid.status_code == 422


def test_g03_weight_target_equals_start_weight_422(client, user):
    """G-03：改后 ``target_value == start_weight_kg`` → 422。"""
    goal = created_goal(create_goal(client, user["header"], goal_type="weight",
                                    target_value=68.0, start_weight_kg=72.5))
    resp = _patch(client, user["header"], goal["id"], target_value=72.5)
    assert resp.status_code == 422
    assert any(e["field"] == "target_value" for e in resp.get_json()["errors"])


def test_g03_soft_warning_not_written_then_confirmed(client, user):
    """G-03：改后超出常见范围 → 200 ``SOFT_WARNING`` 且**未写入**；确认后写入。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    soft = _patch(client, user["header"], goal["id"], target_value=6000)
    assert soft.status_code == 200
    body = soft.get_json()
    assert body["code"] == "SOFT_WARNING"
    assert body["data"]["requires_confirm"] is True
    assert goal_row(goal["id"])["target_value"] == 2000      # 未写入

    confirmed = _patch(client, user["header"], goal["id"], target_value=6000,
                       acknowledge_warnings=True)
    assert confirmed.status_code == 200
    assert confirmed.get_json()["code"] == "OK"
    assert goal_row(goal["id"])["target_value"] == 6000


def test_g03_hard_range_422(client, user):
    """G-03：改后为不可能值 → 422。"""
    goal = created_goal(create_goal(client, user["header"], goal_type="sleep", target_value=8))
    resp = _patch(client, user["header"], goal["id"], target_value=30)
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "VALIDATION_FAILED"


def test_g03_soft_deleted_goal_404(client, user):
    """G-03：软删目标不可编辑 → 404。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    assert client.delete(f"{API}/goals/{goal['id']}",
                         headers=user["header"]).status_code == 200
    resp = _patch(client, user["header"], goal["id"], target_value=2500)
    assert resp.status_code == 404
    assert resp.get_json()["code"] == "RESOURCE_NOT_FOUND"
    assert goal_row(goal["id"])["target_value"] == 2000


def test_g03_cross_user_and_missing_404(client, user, peer):
    """G-03：跨用户 / 不存在 → **统一 404**（不泄露资源是否存在）。"""
    goal = created_goal(create_goal(client, peer["header"],
                                    goal_type="water", target_value=2000))
    cross = _patch(client, user["header"], goal["id"], target_value=2500)
    assert cross.status_code == 404
    assert cross.get_json()["code"] == "RESOURCE_NOT_FOUND"

    missing = _patch(client, user["header"], 99999999, target_value=2500)
    assert missing.status_code == 404
    assert missing.get_json()["code"] == "RESOURCE_NOT_FOUND"
    # 对端数据未受影响
    assert goal_row(goal["id"])["target_value"] == 2000


def test_g03_client_user_id_and_auth(client, user):
    """G-03：``user_id`` 注入 → 400；未认证 → 401。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    injected = _patch(client, user["header"], goal["id"], user_id=1, target_value=2500)
    assert injected.status_code == 400
    assert goal_row(goal["id"])["target_value"] == 2000

    resp = client.patch(f"{API}/goals/{goal['id']}", json={"target_value": 2500})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_g03_date_order_validation(client, user):
    """G-03：``start_date`` 晚于既有 ``target_date`` → 422。"""
    goal = created_goal(create_goal(client, user["header"], goal_type="weight",
                                    target_value=66.0, start_date="2026-01-01",
                                    target_date="2026-12-31"))
    resp = _patch(client, user["header"], goal["id"], start_date="2027-01-01")
    assert resp.status_code == 422
    assert any(e["field"] == "start_date" for e in resp.get_json()["errors"])
