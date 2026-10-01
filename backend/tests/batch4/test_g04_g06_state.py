# -*- coding: utf-8 -*-
"""S2 第四批 —— G-04 暂停 / G-05 恢复 / G-06 删除（软删）。

★ G-06 为 S2 必测项：软删**三件事必须齐全**（``is_deleted`` / ``deleted_at`` /
``deleted_marker = id``），否则用户**永久无法重建同类型目标**。
"""
from __future__ import annotations

from tests.batch4.conftest import (
    API,
    create_goal,
    created_goal,
    goal_row,
    insert_conflicting_active_goal,
)


def test_g04_pause_and_idempotent_changed_flag(client, user):
    """G-04：暂停 200 + ``changed: true``；已暂停再调 → 200 + ``changed: false``。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    first = client.post(f"{API}/goals/{goal['id']}/pause", headers=user["header"])
    assert first.status_code == 200, first.get_json()
    body = first.get_json()
    assert body["message"] == "目标已暂停"
    assert body["data"] == {"id": goal["id"], "status": 0, "changed": True}
    assert goal_row(goal["id"])["status"] == 0

    again = client.post(f"{API}/goals/{goal['id']}/pause", headers=user["header"])
    assert again.status_code == 200
    assert again.get_json()["data"]["changed"] is False
    assert again.get_json()["data"]["status"] == 0


def test_g05_resume_and_idempotent_changed_flag(client, user):
    """G-05：恢复 200 + ``changed: true``；已进行中再调 → ``changed: false``。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="sleep", target_value=8))
    client.post(f"{API}/goals/{goal['id']}/pause", headers=user["header"])

    resumed = client.post(f"{API}/goals/{goal['id']}/resume", headers=user["header"])
    assert resumed.status_code == 200, resumed.get_json()
    assert resumed.get_json()["data"] == {"id": goal["id"], "status": 1, "changed": True}
    assert goal_row(goal["id"])["status"] == 1

    again = client.post(f"{API}/goals/{goal['id']}/resume", headers=user["header"])
    assert again.status_code == 200
    assert again.get_json()["data"]["changed"] is False


def test_g05_resume_conflict_409(client, user):
    """G-05：同类型已有另一条在用目标 → 409 ``GOAL_TYPE_EXISTS``。

    防御性分支：唯一约束 ``uk_goal_user_type_active`` 使 ``deleted_marker=0`` 的同类型行
    只能有 1 条，正常业务路径不可自然构造；本用例以**非零** ``deleted_marker`` 直接写入
    第二条"未软删"目标，验证该分支确实生效（随后由本批清理装置回收）。
    """
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    client.post(f"{API}/goals/{goal['id']}/pause", headers=user["header"])
    row = goal_row(goal["id"])
    insert_conflicting_active_goal(row["user_id"], "water")

    resp = client.post(f"{API}/goals/{goal['id']}/resume", headers=user["header"])
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "GOAL_TYPE_EXISTS"
    assert goal_row(goal["id"])["status"] == 0      # 未被恢复


def test_g04_g05_state_text_reflected_in_list(client, user):
    """G-04/G-05：``status_text`` 与 ``status`` 一致（中性文案）。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    client.post(f"{API}/goals/{goal['id']}/pause", headers=user["header"])
    paused = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"][0]
    assert paused["status"] == 0 and paused["status_text"] == "paused"

    client.post(f"{API}/goals/{goal['id']}/resume", headers=user["header"])
    ongoing = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"][0]
    assert ongoing["status"] == 1 and ongoing["status_text"] == "ongoing"


def test_g04_g05_cross_user_and_missing_404(client, user, peer):
    """G-04/G-05：跨用户 / 不存在 → 统一 404。"""
    theirs = created_goal(create_goal(client, peer["header"],
                                      goal_type="water", target_value=2000))
    for action in ("pause", "resume"):
        resp = client.post(f"{API}/goals/{theirs['id']}/{action}", headers=user["header"])
        assert resp.status_code == 404, (action, resp.status_code)
        assert resp.get_json()["code"] == "RESOURCE_NOT_FOUND"
        gone = client.post(f"{API}/goals/99999999/{action}", headers=user["header"])
        assert gone.status_code == 404
    # 对端状态未被改动
    assert goal_row(theirs["id"])["status"] == 1


def test_g04_g05_client_user_id_and_auth(client, user):
    """G-04/G-05：``user_id`` 注入 → 400；未认证 → 401。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    injected = client.post(f"{API}/goals/{goal['id']}/pause?user_id=1",
                           headers=user["header"])
    assert injected.status_code == 400
    assert goal_row(goal["id"])["status"] == 1

    assert client.post(f"{API}/goals/{goal['id']}/pause").status_code == 401


# ════════════════════════════════════════════════════════════════════
# G-06 删除（软删三件事 —— S2 必测项）
# ════════════════════════════════════════════════════════════════════
def test_g06_soft_delete_three_things_and_physical_row_kept(client, user):
    """G-06：200 ``deleted_count: 1``；**三件事齐全**；物理行保留。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    resp = client.delete(f"{API}/goals/{goal['id']}", headers=user["header"])
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["message"] == "已删除"
    assert body["data"] == {"deleted_count": 1}

    row = goal_row(goal["id"])
    assert row is not None, "物理行被删除（禁止物理删除）"
    assert row["is_deleted"] == 1
    assert row["deleted_at"] is not None
    assert row["deleted_marker"] == row["id"], "deleted_marker 未写为 id（唯一约束无法释放）"


def test_g06_soft_deleted_invisible_and_repeat_404(client, user):
    """G-06：软删后默认不可见；重复删除 → 404。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    client.delete(f"{API}/goals/{goal['id']}", headers=user["header"])

    assert client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"] == []
    shown = client.get(f"{API}/goals", headers=user["header"],
                       query_string={"include_history": "true"}).get_json()["data"]["items"]
    assert [i["id"] for i in shown] == [goal["id"]]
    assert shown[0]["status_text"] == "archived"

    repeat = client.delete(f"{API}/goals/{goal['id']}", headers=user["header"])
    assert repeat.status_code == 404
    assert repeat.get_json()["code"] == "RESOURCE_NOT_FOUND"
    # 历史行不可经 G-03/G-04/G-05 变更
    assert client.patch(f"{API}/goals/{goal['id']}", headers=user["header"],
                        json={"target_value": 2500}).status_code == 404
    assert client.post(f"{API}/goals/{goal['id']}/pause",
                       headers=user["header"]).status_code == 404


def test_g06_rebuild_same_type_immediately(client, user):
    """G-06 ★：软删后**同类型可立即重建**（``deleted_marker`` 已释放唯一约束）。"""
    old = created_goal(create_goal(client, user["header"],
                                   goal_type="weight", target_value=68.0,
                                   start_weight_kg=72.5))
    assert client.delete(f"{API}/goals/{old['id']}", headers=user["header"]).status_code == 200

    new = create_goal(client, user["header"], goal_type="weight",
                      target_value=66.0, start_weight_kg=72.5)
    assert new.status_code == 201, new.get_json()
    fresh = created_goal(new)
    assert fresh["id"] != old["id"]
    assert goal_row(fresh["id"])["deleted_marker"] == 0

    items = client.get(f"{API}/goals", headers=user["header"]).get_json()["data"]["items"]
    assert [i["id"] for i in items] == [fresh["id"]]


def test_g06_cross_user_and_missing_404(client, user, peer):
    """G-06：跨用户 / 不存在 → 404；他人数据不被软删。"""
    theirs = created_goal(create_goal(client, peer["header"],
                                      goal_type="water", target_value=2000))
    cross = client.delete(f"{API}/goals/{theirs['id']}", headers=user["header"])
    assert cross.status_code == 404
    assert cross.get_json()["code"] == "RESOURCE_NOT_FOUND"
    assert goal_row(theirs["id"])["is_deleted"] == 0

    assert client.delete(f"{API}/goals/99999999",
                         headers=user["header"]).status_code == 404


def test_g06_client_user_id_and_auth(client, user):
    """G-06：``user_id`` 注入 → 400；未认证 → 401。"""
    goal = created_goal(create_goal(client, user["header"],
                                    goal_type="water", target_value=2000))
    injected = client.delete(f"{API}/goals/{goal['id']}?user_id=1", headers=user["header"])
    assert injected.status_code == 400
    assert goal_row(goal["id"])["is_deleted"] == 0

    assert client.delete(f"{API}/goals/{goal['id']}").status_code == 401
