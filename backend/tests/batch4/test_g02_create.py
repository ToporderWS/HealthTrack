# -*- coding: utf-8 -*-
"""S2 第四批 —— G-02 创建目标。

覆盖：四类创建（``period_type`` / ``unit`` 服务端强制） / 字段禁传 / ``attr_1`` 必填 /
``weight`` 一致性 / ``auto_start_weight`` / 重复类型 409 / 软删后重建 /
软提示（未写入 → 确认后写入） / 硬拦截 / ``user_id`` 注入 / 未认证。
"""
from __future__ import annotations

from tests.batch4.conftest import (
    API,
    create_goal,
    created_goal,
    dt_at,
    fmt,
    goal_row,
    post_record,
)


def test_g02_create_four_types_server_forced_fields(client, user):
    """G-02：四类目标 201；``period_type`` / ``unit`` 由服务端强制填充。"""
    cases = (
        ({"goal_type": "weight", "target_value": 68.0, "start_weight_kg": 72.5},
         {"period_type": "once", "unit": "kg", "attr_1": None}),
        ({"goal_type": "water", "target_value": 2000},
         {"period_type": "daily", "unit": "ml", "attr_1": None}),
        ({"goal_type": "sport", "target_value": 150, "attr_1": "min"},
         {"period_type": "weekly", "unit": "min", "attr_1": "min"}),
        ({"goal_type": "sleep", "target_value": 8},
         {"period_type": "daily", "unit": "hour", "attr_1": None}),
    )
    for payload, expected in cases:
        resp = create_goal(client, user["header"], **payload)
        assert resp.status_code == 201, (payload, resp.get_json())
        body = resp.get_json()
        assert body["code"] == "OK" and body["message"] == "目标已创建"
        goal = body["data"]["goal"]
        for key, value in expected.items():
            assert goal[key] == value, (payload, key, goal[key])
        assert goal["status"] == 1 and goal["status_text"] == "ongoing"
        assert goal["start_date"] is not None


def test_g02_sport_count_unit_follows_attr(client, user):
    """G-02：``sport`` 的 ``unit`` 随 ``attr_1``（``count`` → ``count``）。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="sport", target_value=3, attr_1="count"))
    assert goal["unit"] == "count"
    assert goal["period_type"] == "weekly"
    assert goal["attr_1"] == "count"


def test_g02_sport_count_conflicts_with_sport_min(client, user):
    """G-02：``sport`` 已有在用目标 → 再建（即使 ``attr_1`` 不同）→ 409。"""
    created_goal(create_goal(client, user["header"],
                             goal_type="sport", target_value=150, attr_1="min"))
    resp = create_goal(client, user["header"], goal_type="sport", target_value=3, attr_1="count")
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "GOAL_TYPE_EXISTS"


def test_g02_period_type_mismatch_422(client, user):
    """G-02：客户端 ``period_type`` 与服务端强制值不一致 → 422。"""
    resp = create_goal(client, user["header"], goal_type="water", target_value=2000,
                       period_type="weekly")
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert any(e["field"] == "period_type" for e in body["errors"])

    ok = create_goal(client, user["header"], goal_type="water", target_value=2000,
                     period_type="daily")
    assert ok.status_code == 201


def test_g02_unit_mismatch_422(client, user):
    """G-02：客户端 ``unit`` 与服务端取值不一致 → 422。"""
    resp = create_goal(client, user["header"], goal_type="water", target_value=2000, unit="L")
    assert resp.status_code == 422
    assert any(e["field"] == "unit" for e in resp.get_json()["errors"])


def test_g02_forbidden_fields_422(client, user):
    """G-02：非 weight 传 ``target_date`` / ``start_weight_kg`` / ``auto_start_weight`` → 422。"""
    bad_date = create_goal(client, user["header"], goal_type="water", target_value=2000,
                           target_date="2026-12-31")
    assert bad_date.status_code == 422
    assert any(e["field"] == "target_date" for e in bad_date.get_json()["errors"])

    bad_weight = create_goal(client, user["header"], goal_type="sleep", target_value=8,
                             start_weight_kg=70.0)
    assert bad_weight.status_code == 422
    assert any(e["field"] == "start_weight_kg" for e in bad_weight.get_json()["errors"])

    bad_auto = create_goal(client, user["header"], goal_type="water", target_value=2000,
                           auto_start_weight=True)
    assert bad_auto.status_code == 422
    assert any(e["field"] == "auto_start_weight" for e in bad_auto.get_json()["errors"])

    bad_attr = create_goal(client, user["header"], goal_type="weight", target_value=68.0,
                           attr_1="count")
    assert bad_attr.status_code == 422
    assert any(e["field"] == "attr_1" for e in bad_attr.get_json()["errors"])


def test_g02_sport_attr1_required_and_restricted(client, user):
    """G-02：``sport`` 的 ``attr_1`` **必填**且取值受限。"""
    missing = create_goal(client, user["header"], goal_type="sport", target_value=150)
    assert missing.status_code == 422
    assert any(e["field"] == "attr_1" and e["code"] == "REQUIRED"
               for e in missing.get_json()["errors"])

    invalid = create_goal(client, user["header"], goal_type="sport", target_value=150,
                          attr_1="times")
    assert invalid.status_code == 422
    assert any(e["field"] == "attr_1" for e in invalid.get_json()["errors"])


def test_g02_weight_target_equals_start_weight_422(client, user):
    """G-02：``weight`` 的 ``target_value == start_weight_kg`` → 422（完成度无意义）。"""
    resp = create_goal(client, user["header"], goal_type="weight",
                       target_value=72.5, start_weight_kg=72.5)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert any(e["field"] == "target_value" for e in body["errors"])


def test_g02_auto_start_weight_from_latest_record(client, ready_user):
    """G-02：``auto_start_weight=true`` → 服务端取**最近一条**体重记录填充。"""
    resp = post_record(client, ready_user["header"],
                       {"metric_type": "weight", "value_1": 71.0,
                        "recorded_at": fmt(dt_at(-3, 7, 0))})
    assert resp.status_code == 201, resp.get_json()
    assert post_record(client, ready_user["header"],
                       {"metric_type": "weight", "value_1": 70.4,
                        "recorded_at": fmt(dt_at(-1, 7, 0))}).status_code == 201

    goal = created_goal(create_goal(client, ready_user["header"], goal_type="weight",
                                    target_value=66.0, auto_start_weight=True))
    assert goal["start_weight_kg"] == 70.4

    row = goal_row(goal["id"])
    assert float(row["start_weight_kg"]) == 70.4


def test_g02_auto_start_weight_without_record_422(client, user):
    """G-02：``auto_start_weight=true`` 但**无体重记录** → 422（**不估算**）。"""
    resp = create_goal(client, user["header"], goal_type="weight",
                       target_value=66.0, auto_start_weight=True)
    assert resp.status_code == 422
    assert any(e["field"] == "start_weight_kg" for e in resp.get_json()["errors"])


def test_g02_weight_without_start_weight_allowed(client, user):
    """G-02：``weight`` 未提供起始体重且未开启 auto → 允许创建（完成度将为 null）。"""
    goal = created_goal(create_goal(client, user["header"], goal_type="weight",
                                    target_value=66.0))
    assert goal["start_weight_kg"] is None
    progress = client.get(f"{API}/goals/progress", headers=user["header"]).get_json()
    assert progress["data"]["items"][0]["progress_percent"] is None


def test_g02_duplicate_type_409_and_rebuild_after_soft_delete(client, user):
    """G-02：同类在用目标 → 409；**软删后（``deleted_marker`` 释放）可立即重建**。"""
    first = created_goal(create_goal(client, user["header"],
                                     goal_type="water", target_value=2000))
    dup = create_goal(client, user["header"], goal_type="water", target_value=2500)
    assert dup.status_code == 409
    assert dup.get_json()["code"] == "GOAL_TYPE_EXISTS"

    assert client.delete(f"{API}/goals/{first['id']}",
                         headers=user["header"]).status_code == 200
    rebuilt = create_goal(client, user["header"], goal_type="water", target_value=2500)
    assert rebuilt.status_code == 201, rebuilt.get_json()
    row = goal_row(created_goal(rebuilt)["id"])
    assert row["is_deleted"] == 0 and row["deleted_marker"] == 0


def test_g02_soft_warning_200_not_written_then_confirmed(client, user):
    """G-02：目标值超出常见范围 → 200 ``SOFT_WARNING`` 且**本次不写入**；确认后写入。"""
    soft = create_goal(client, user["header"], goal_type="weight", target_value=310,
                       start_weight_kg=320)
    assert soft.status_code == 200, soft.get_json()
    body = soft.get_json()
    assert body["code"] == "SOFT_WARNING"
    assert body["data"]["requires_confirm"] is True
    warnings = body["data"]["warnings"]
    assert warnings and warnings[0]["code"] == "OUT_OF_COMMON_RANGE"
    assert warnings[0]["message"] == "该数值超出常见录入范围，请确认是否输错"
    assert "errors" not in body
    # 软提示响应不得回显区间边界
    assert "20" not in warnings[0]["message"] and "300" not in warnings[0]["message"]
    # 未写入
    assert client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"] == []

    confirmed = create_goal(client, user["header"], goal_type="weight", target_value=310,
                            start_weight_kg=320, acknowledge_warnings=True)
    assert confirmed.status_code == 201, confirmed.get_json()
    items = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    assert len(items) == 1 and items[0]["target_value"] == 310


def test_g02_hard_range_422(client, user):
    """G-02：不可能值 → 422 硬拦截（四类 + sport 两种计量方式）。"""
    cases = (
        {"goal_type": "weight", "target_value": 600, "start_weight_kg": 72.0},
        {"goal_type": "water", "target_value": 25000},
        {"goal_type": "sleep", "target_value": 30},
        {"goal_type": "sport", "target_value": 80, "attr_1": "count"},
        {"goal_type": "sport", "target_value": 20000, "attr_1": "min"},
        {"goal_type": "weight", "target_value": 0, "start_weight_kg": 72.0},
    )
    for payload in cases:
        resp = create_goal(client, user["header"], **payload)
        assert resp.status_code == 422, (payload, resp.get_json())
        assert resp.get_json()["code"] == "VALIDATION_FAILED"


def test_g02_required_fields_400(client, user):
    """G-02：``goal_type`` / ``target_value`` 缺失 → 400（携带字段级 ``errors[]``）。"""
    missing_type = create_goal(client, user["header"], target_value=2000)
    assert missing_type.status_code == 400
    body = missing_type.get_json()
    assert body["code"] == "INVALID_PARAM"
    assert body["errors"][0]["code"] == "REQUIRED"

    missing_value = create_goal(client, user["header"], goal_type="water")
    assert missing_value.status_code == 400
    assert missing_value.get_json()["errors"][0]["code"] == "REQUIRED"

    invalid_type = create_goal(client, user["header"], goal_type="bp", target_value=1)
    assert invalid_type.status_code == 422
    assert invalid_type.get_json()["errors"][0]["field"] == "goal_type"


def test_g02_date_validation(client, user):
    """G-02：``start_date`` > ``target_date`` → 422；日期格式非法 → 422。"""
    bad_order = create_goal(client, user["header"], goal_type="weight", target_value=66.0,
                            start_date="2026-12-31", target_date="2026-01-01")
    assert bad_order.status_code == 422
    assert any(e["field"] == "start_date" for e in bad_order.get_json()["errors"])

    bad_format = create_goal(client, user["header"], goal_type="weight", target_value=66.0,
                             target_date="2026/12/31")
    assert bad_format.status_code == 422
    assert any(e["field"] == "target_date" for e in bad_format.get_json()["errors"])


def test_g02_client_user_id_rejected(client, user):
    """G-02：请求体 / query 出现 ``user_id`` → 400 ``INVALID_PARAM``。"""
    in_body = create_goal(client, user["header"], goal_type="water", target_value=2000,
                          user_id=1)
    assert in_body.status_code == 400
    assert in_body.get_json()["code"] == "INVALID_PARAM"

    in_query = client.post(f"{API}/goals?user_id=1", headers=user["header"],
                           json={"goal_type": "water", "target_value": 2000})
    assert in_query.status_code == 400
    assert in_query.get_json()["code"] == "INVALID_PARAM"

    # 注入被拒后无任何写入
    assert client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"] == []


def test_g02_requires_auth(client):
    """G-02：未认证 → 401。"""
    resp = client.post(f"{API}/goals", json={"goal_type": "water", "target_value": 2000})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_g02_cross_user_isolation(client, user, peer):
    """G-02：目标严格归属当前登录用户（两账号互不可见）。"""
    created_goal(create_goal(client, user["header"], goal_type="water", target_value=2000))
    created_goal(create_goal(client, peer["header"], goal_type="water", target_value=3000))
    mine = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    theirs = client.get(f"{API}/goals", headers=peer["header"]).get_json()["data"]["items"]
    assert [i["target_value"] for i in mine] == [2000]
    assert [i["target_value"] for i in theirs] == [3000]
