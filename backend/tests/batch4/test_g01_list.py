# -*- coding: utf-8 -*-
"""S2 第四批 —— G-01 目标列表。

覆盖：空列表（非 404） / 四类目标 / ``goal_type`` 过滤 / ``include_paused`` /
``include_history``（``status_text = archived``）/ 排序（显式 ORDER BY）/
软删字段不暴露 / 非法 ``goal_type`` → 400 / 未认证 → 401。
"""
from __future__ import annotations

from tests.batch4.conftest import API, create_goal, created_goal, goal_row

ALL_TYPES = ("weight", "water", "sport", "sleep")


def _seed_four(client, header):
    """创建 4 类目标，返回 ``{goal_type: goal}``。"""
    payloads = {
        "weight": {"goal_type": "weight", "target_value": 68.0, "start_weight_kg": 72.5},
        "water": {"goal_type": "water", "target_value": 2000},
        "sport": {"goal_type": "sport", "target_value": 150, "attr_1": "min"},
        "sleep": {"goal_type": "sleep", "target_value": 8},
    }
    out = {}
    for key, payload in payloads.items():
        out[key] = created_goal(create_goal(client, header, **payload))
    return out


def test_g01_empty_list_is_not_404(client, user):
    """G-01：无目标 → ``items: []``（**不是 404**，服务端不返回"未设目标"文案）。"""
    resp = client.get(f"{API}/goals", headers=user["header"])
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK"
    assert body["data"] == {"items": []}
    assert "未设" not in body["message"]


def test_g01_returns_four_types_ordered_by_goal_type(client, user):
    """G-01：四类目标齐全，且**显式**按 ``goal_type ASC`` 排序。"""
    _seed_four(client, user["header"])
    body = client.get(f"{API}/goals", headers=user["header"]).get_json()
    items = body["data"]["items"]
    assert len(items) == 4
    assert [i["goal_type"] for i in items] == sorted(ALL_TYPES)
    # 显式排序不依赖索引顺序：连续两次请求顺序一致
    again = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    assert [i["id"] for i in again] == [i["id"] for i in items]


def test_g01_item_shape_and_no_soft_delete_fields(client, user):
    """G-01：条目字段齐全；``is_deleted`` / ``deleted_marker`` **不暴露**。"""
    _seed_four(client, user["header"])
    items = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    expected_keys = {"id", "goal_type", "period_type", "target_value", "unit", "attr_1",
                     "start_weight_kg", "start_date", "target_date", "status",
                     "status_text", "created_at"}
    for item in items:
        assert set(item.keys()) == expected_keys, item
        assert "is_deleted" not in item and "deleted_marker" not in item
        assert "deleted_at" not in item
    water = next(i for i in items if i["goal_type"] == "water")
    assert water["period_type"] == "daily" and water["unit"] == "ml"
    assert water["status"] == 1 and water["status_text"] == "ongoing"
    sport = next(i for i in items if i["goal_type"] == "sport")
    assert sport["unit"] == "min" and sport["attr_1"] == "min"


def test_g01_goal_type_filter(client, user):
    """G-01：``goal_type`` 过滤；非法值 → 400（参数层，非语义层）。"""
    _seed_four(client, user["header"])
    body = client.get(f"{API}/goals", headers=user["header"],
                      query_string={"goal_type": "water"}).get_json()
    assert [i["goal_type"] for i in body["data"]["items"]] == ["water"]

    bad = client.get(f"{API}/goals", headers=user["header"],
                     query_string={"goal_type": "bp"})
    assert bad.status_code == 400
    assert bad.get_json()["code"] == "INVALID_PARAM"


def test_g01_include_paused(client, user):
    """G-01：``include_paused`` 两态（默认 ``true``）。"""
    goals = _seed_four(client, user["header"])
    assert client.post(f"{API}/goals/{goals['water']['id']}/pause",
                       headers=user["header"]).status_code == 200

    default_items = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    assert len(default_items) == 4
    assert any(i["status"] == 0 and i["status_text"] == "paused" for i in default_items)

    only_on = client.get(f"{API}/goals", headers=user["header"],
                         query_string={"include_paused": "false"}).get_json()["data"]["items"]
    assert len(only_on) == 3
    assert all(i["status"] == 1 for i in only_on)


def test_g01_include_history_and_archived_status_text(client, user):
    """G-01：``include_history`` 两态；历史行 ``status_text = archived`` 且只读。"""
    goals = _seed_four(client, user["header"])
    target_id = goals["weight"]["id"]
    assert client.delete(f"{API}/goals/{target_id}", headers=user["header"]).status_code == 200

    hidden = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    assert len(hidden) == 3
    assert all(i["id"] != target_id for i in hidden)

    shown = client.get(f"{API}/goals", headers=user["header"],
                       query_string={"include_history": "true"}).get_json()["data"]["items"]
    assert len(shown) == 4
    archived = next(i for i in shown if i["id"] == target_id)
    assert archived["status_text"] == "archived"
    assert "is_deleted" not in archived and "deleted_marker" not in archived

    # 过滤参数与历史组合
    filtered = client.get(f"{API}/goals", headers=user["header"],
                          query_string={"include_history": "true",
                                        "goal_type": "weight"}).get_json()["data"]["items"]
    assert [i["id"] for i in filtered] == [target_id]


def test_g01_history_ordered_by_created_at_desc(client, user):
    """G-01：历史行按 ``created_at DESC, id DESC``（显式 ORDER BY）。"""
    first = created_goal(create_goal(client, user["header"],
                                     goal_type="water", target_value=2000))
    client.delete(f"{API}/goals/{first['id']}", headers=user["header"])
    second = created_goal(create_goal(client, user["header"],
                                      goal_type="water", target_value=2500))
    client.delete(f"{API}/goals/{second['id']}", headers=user["header"])

    items = client.get(f"{API}/goals", headers=user["header"],
                       query_string={"include_history": "true"}).get_json()["data"]["items"]
    assert items[0]["id"] == second["id"]
    assert items[1]["id"] == first["id"]
    # 两条历史行均只读（status_text = archived）
    assert {i["status_text"] for i in items} == {"archived"}


def test_g01_invalid_boolean_param_rejected(client, user):
    """G-01：``include_paused`` 非法布尔值 → 400。"""
    resp = client.get(f"{API}/goals", headers=user["header"],
                      query_string={"include_paused": "maybe"})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "INVALID_PARAM"


def test_g01_requires_auth(client):
    """G-01：未认证 → 401（不泄露任何业务信息）。"""
    resp = client.get(f"{API}/goals")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_g01_physical_row_untouched_by_read(client, user):
    """G-01：只读操作不改变物理行。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="sleep", target_value=8))
    before = goal_row(goal["id"])
    client.get(f"{API}/goals", headers=user["header"], query_string={"include_history": "true"})
    assert goal_row(goal["id"]) == before
