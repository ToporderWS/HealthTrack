# -*- coding: utf-8 -*-
"""S2 第七批 D-02（``POST /api/v1/me/data/clear``）验收用例。

覆盖：鉴权 / 三重确认（确认文字 + 密码 + 不可恢复声明）/ 密码错误**不计数、不 429** /
4 类清理范围 / 记录-标签-目标软删（``deleted_marker = id``）/ 档案 6 健康字段置空**保留档案行** /
账号·会话·登录失败·导出任务**不受影响** / 二次执行 0 条 / 越权隔离 / 事务失败整体回滚 /
禁止范围扩展参数 / envelope 与错误码契约。

★ 全部用例**只**操作 ``tst`` 独立测试账号；不对任何非测试账号执行清空。
"""
from __future__ import annotations

from tests.batch7.conftest import (
    account_row,
    add_goal,
    add_record,
    clear,
    confirm_payload,
    fill_profile,
    goal_rows,
    insert_job,
    job_rows,
    login_failure_rows,
    profile_row,
    record_rows,
    session_rows,
    tag_rows,
    ts_before,
)

SCOPE = ["health_records", "record_tags", "goals", "profile_health_fields"]
CLEAR_KEYS = {"deleted_records", "deleted_tags", "deleted_goals",
              "profile_health_fields_cleared", "account_kept", "scope"}
HEALTH_FIELDS = ("height_cm", "initial_weight_kg", "blood_type",
                 "medical_history", "allergy_history", "medication_notes")

#: rich_user 的活跃记录数（weight / water / mood；heart 已软删）
RICH_ACTIVE_RECORDS = 3


def _cleared(client, header, password, **overrides):
    resp = clear(client, header, **confirm_payload(password, **overrides))
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _active_records(user_id):
    return [r for r in record_rows(user_id) if r["is_deleted"] == 0]


# ════════════════════════════════════════════════════════════════════
# 鉴权
# ════════════════════════════════════════════════════════════════════
def test_d02_requires_auth(client):
    """无 Token → ``401 UNAUTHENTICATED``（**不得**因为缺参先返回 400）。"""
    resp = client.post("/api/v1/me/data/clear", json=confirm_payload())
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_d02_bad_token(client):
    resp = client.post("/api/v1/me/data/clear",
                       headers={"Authorization": "Bearer nope"},
                       json=confirm_payload())
    assert resp.status_code == 401


def test_d02_no_body_is_invalid_param(client, user):
    """无 JSON 体 → ``400 INVALID_PARAM``。"""
    resp = client.post("/api/v1/me/data/clear", headers=user["header"])
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"


# ════════════════════════════════════════════════════════════════════
# 三重确认
# ════════════════════════════════════════════════════════════════════
def test_d02_confirm_text_wrong(client, rich_user):
    """确认文字不正确 → ``422 VALIDATION_FAILED`` + ``errors[].field = confirm_text``。"""
    resp = clear(client, rich_user["header"],
                 confirm_text="删除", password=rich_user["password"],
                 acknowledge_irreversible=True)
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert [e["field"] for e in body["errors"]] == ["confirm_text"]
    assert len(_active_records(rich_user["user_id"])) == RICH_ACTIVE_RECORDS


def test_d02_confirm_text_missing(client, rich_user):
    """缺少确认文字 → ``422 VALIDATION_FAILED``。"""
    resp = clear(client, rich_user["header"], password=rich_user["password"],
                 acknowledge_irreversible=True)
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "VALIDATION_FAILED"


def test_d02_ack_missing(client, rich_user):
    """缺少不可恢复声明 → ``422`` 且字段为 ``acknowledge_irreversible``。"""
    resp = clear(client, rich_user["header"], confirm_text="确认删除",
                 password=rich_user["password"])
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert [e["field"] for e in body["errors"]] == ["acknowledge_irreversible"]


def test_d02_ack_false(client, rich_user):
    """``acknowledge_irreversible=false`` → ``422``。"""
    resp = clear(client, rich_user["header"], confirm_text="确认删除",
                 password=rich_user["password"], acknowledge_irreversible=False)
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "VALIDATION_FAILED"


def test_d02_ack_string_true_rejected(client, rich_user):
    """``acknowledge_irreversible="true"``（字符串）**不算**已确认 → ``422``。"""
    resp = clear(client, rich_user["header"], confirm_text="确认删除",
                 password=rich_user["password"], acknowledge_irreversible="true")
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "VALIDATION_FAILED"


def test_d02_confirm_before_password(client, rich_user):
    """确认文字错误时**先**返回 ``VALIDATION_FAILED``（不消耗密码校验）。"""
    resp = clear(client, rich_user["header"], confirm_text="x", password="wrong-pwd",
                 acknowledge_irreversible=True)
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "VALIDATION_FAILED"


def test_d02_password_wrong(client, rich_user):
    """密码错误 → ``422 PASSWORD_INVALID``（**且不清空任何数据**）。"""
    resp = clear(client, rich_user["header"], **confirm_payload("definitely-wrong"))
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["code"] == "PASSWORD_INVALID"
    assert len(_active_records(rich_user["user_id"])) == RICH_ACTIVE_RECORDS
    assert profile_row(rich_user["user_id"])["height_cm"] is not None


def test_d02_password_empty(client, rich_user):
    """密码为空 → ``422 VALIDATION_FAILED`` + ``field = password``。"""
    resp = clear(client, rich_user["header"], **confirm_payload(""))
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert [e["field"] for e in body["errors"]] == ["password"]


# ════════════════════════════════════════════════════════════════════
# C1 冻结：密码错误**不累计失败次数、不返回 429**
# ════════════════════════════════════════════════════════════════════
def test_d02_wrong_password_never_429_and_no_counter(client, rich_user):
    """连续 5 次密码错误：**每次都是 422 PASSWORD_INVALID**（不出现 429）；
    会话 ``export_pwd_fail_count`` 不变；**不写** ``login_failure_state``。"""
    before = session_rows(rich_user["user_id"])
    assert len(before) == 1

    codes = []
    for _ in range(5):
        resp = clear(client, rich_user["header"], **confirm_payload("wrong-pwd-123"))
        codes.append((resp.status_code, resp.get_json()["code"]))

    assert codes == [(422, "PASSWORD_INVALID")] * 5, codes
    after = session_rows(rich_user["user_id"])
    assert [r["export_pwd_fail_count"] for r in after] == [0]
    assert [r["revoked_at"] for r in after] == [None]
    assert login_failure_rows(rich_user["username"]) == []


def test_d02_account_not_locked_after_many_wrong_passwords(client, rich_user):
    """错误密码后**仍可正常登录**（证明未触发任何锁定机制）。"""
    for _ in range(4):
        clear(client, rich_user["header"], **confirm_payload("wrong-pwd-xyz"))

    resp = client.post("/api/v1/auth/login", json={
        "username": rich_user["username"], "password": rich_user["password"],
    })
    assert resp.status_code == 200, resp.get_json()


# ════════════════════════════════════════════════════════════════════
# 成功响应契约
# ════════════════════════════════════════════════════════════════════
def test_d02_success_shape_and_scope(client, rich_user):
    """成功 ``200``：6 键；``scope`` **逐字逐序**冻结；``account_kept = true``。"""
    body = _cleared(client, rich_user["header"], rich_user["password"])
    assert set(body["data"].keys()) == CLEAR_KEYS, body["data"]
    assert body["data"]["scope"] == SCOPE
    assert body["data"]["account_kept"] is True
    assert body["code"] == "OK"
    assert set(body.keys()) == {"code", "message", "data", "request_id"}


def test_d02_success_message_and_counts(client, rich_user):
    """文案为冻结形态；计数与实际数据一致。"""
    body = _cleared(client, rich_user["header"], rich_user["password"])
    data = body["data"]
    assert body["message"] == "已清除 3 条记录。账号保留，数据已按规则清除"
    assert data["deleted_records"] == 3
    assert data["deleted_tags"] == 2
    assert data["deleted_goals"] == 2
    assert data["profile_health_fields_cleared"] == 3


# ════════════════════════════════════════════════════════════════════
# 4 类清理范围（逐类验证）
# ════════════════════════════════════════════════════════════════════
def test_d02_records_soft_deleted_physical_rows_kept(client, rich_user):
    """``health_record`` **软删**（``is_deleted=1`` + ``deleted_at``）；物理行**保留**。"""
    before = record_rows(rich_user["user_id"])
    _cleared(client, rich_user["header"], rich_user["password"])
    after = record_rows(rich_user["user_id"])

    assert len(after) == len(before) == 4
    assert [r["is_deleted"] for r in after] == [1, 1, 1, 1]
    assert all(r["deleted_at"] is not None for r in after)


def test_d02_tags_soft_deleted_with_records(client, rich_user):
    """``record_tag`` **随主记录同步软删**；物理行保留。"""
    before = tag_rows(rich_user["user_id"])
    assert len(before) == 2
    _cleared(client, rich_user["header"], rich_user["password"])
    after = tag_rows(rich_user["user_id"])

    assert len(after) == 2
    assert [t["is_deleted"] for t in after] == [1, 1]
    assert all(t["deleted_at"] is not None for t in after)
    assert {t["tag_value"] for t in after} == {"relaxed", "focused"}


def test_d02_goals_soft_deleted_with_deleted_marker(client, rich_user):
    """``health_goal`` 软删 **+ ``deleted_marker = id``**。"""
    before = goal_rows(rich_user["user_id"])
    assert len(before) == 2
    _cleared(client, rich_user["header"], rich_user["password"])
    after = goal_rows(rich_user["user_id"])

    assert len(after) == 2
    for row in after:
        assert row["is_deleted"] == 1
        assert row["deleted_at"] is not None
        assert row["deleted_marker"] == row["id"], row


def test_d02_goal_unique_constraint_released(client, rich_user):
    """``deleted_marker=id`` 释放唯一约束 ⇒ 清空后**可立即重建**同类目标。"""
    _cleared(client, rich_user["header"], rich_user["password"])
    add_goal(rich_user["user_id"], goal_type="water", status=1)   # 唯一键冲突则测试失败
    active = [g for g in goal_rows(rich_user["user_id"]) if g["is_deleted"] == 0]
    assert len(active) == 1 and active[0]["goal_type"] == "water"


def test_d02_profile_health_fields_null_row_kept(client, rich_user):
    """``user_profile``：6 个健康字段置 **NULL**；**档案行与昵称/性别/出生日期保留**。"""
    before = profile_row(rich_user["user_id"])
    assert before["nickname"] == "测试昵称"
    _cleared(client, rich_user["header"], rich_user["password"])
    after = profile_row(rich_user["user_id"])

    assert after is not None, "档案行不得被删除"
    for field in HEALTH_FIELDS:
        assert after[field] is None, (field, after[field])
    assert after["nickname"] == before["nickname"]
    assert after["gender"] == before["gender"]
    assert after["birth_date"] == before["birth_date"]


def test_d02_keep_fields_when_health_fields_empty(client, user):
    """健康字段本就为空时 cleared = 0；昵称等仍保留。"""
    fill_profile(user["user_id"], keep=True)
    body = _cleared(client, user["header"], user["password"])
    assert body["data"]["profile_health_fields_cleared"] == 0
    assert body["data"]["deleted_records"] == 0
    assert profile_row(user["user_id"])["nickname"] == "测试昵称"


def test_d02_absent_profile_row(client, user):
    """无档案行时**不报错**：cleared = 0（也不新建行）。"""
    body = _cleared(client, user["header"], user["password"])
    assert body["data"]["profile_health_fields_cleared"] == 0
    assert profile_row(user["user_id"]) is None


# ════════════════════════════════════════════════════════════════════
# **不得触碰**的对象（账号 / 会话 / 登录失败 / 导出任务）
# ════════════════════════════════════════════════════════════════════
def test_d02_account_kept_and_still_usable(client, rich_user):
    """``user_account`` 保留，Token 仍有效（可继续调用接口）。"""
    before = account_row(rich_user["user_id"])
    _cleared(client, rich_user["header"], rich_user["password"])
    after = account_row(rich_user["user_id"])

    assert after == before
    resp = client.get("/api/v1/me/data/summary", headers=rich_user["header"])
    assert resp.status_code == 200, resp.get_json()


def test_d02_sessions_untouched(client, rich_user):
    """``user_session`` **不受影响**（不删除、不失效）。"""
    before = session_rows(rich_user["user_id"])
    _cleared(client, rich_user["header"], rich_user["password"])
    assert session_rows(rich_user["user_id"]) == before


def test_d02_export_jobs_untouched(client, rich_user):
    """``export_job`` **不受影响**（行与状态不变；导出文件不在本接口范围内）。"""
    job_id = insert_job(rich_user["user_id"], status="downloaded", record_count=7)
    before = job_rows(rich_user["user_id"])
    assert [j["id"] for j in before] == [job_id]

    _cleared(client, rich_user["header"], rich_user["password"])
    after = job_rows(rich_user["user_id"])

    assert after == before
    assert after[0]["status"] == "downloaded" and after[0]["record_count"] == 7


def test_d02_login_failure_state_untouched(client, rich_user):
    """``login_failure_state`` **不受影响**（清空前后一致）。"""
    before = login_failure_rows(rich_user["username"])
    _cleared(client, rich_user["header"], rich_user["password"])
    assert login_failure_rows(rich_user["username"]) == before


def test_d02_health_goal_rows_kept_physically(client, rich_user):
    """目标物理行保留（软删语义，非物理删除）。"""
    _cleared(client, rich_user["header"], rich_user["password"])
    assert len(goal_rows(rich_user["user_id"])) == 2


# ════════════════════════════════════════════════════════════════════
# 幂等 / 二次执行
# ════════════════════════════════════════════════════════════════════
def test_d02_second_call_returns_zero(client, rich_user):
    """条件驱动幂等：二次执行 → 全部「已清除 0 条」。"""
    first = _cleared(client, rich_user["header"], rich_user["password"])
    assert first["data"]["deleted_records"] == 3

    second = _cleared(client, rich_user["header"], rich_user["password"])
    assert second["message"] == "已清除 0 条记录。账号保留，数据已按规则清除"
    assert second["data"] == {
        "deleted_records": 0, "deleted_tags": 0, "deleted_goals": 0,
        "profile_health_fields_cleared": 0, "account_kept": True, "scope": SCOPE,
    }


def test_d02_summary_zero_after_clear(client, rich_user):
    """清空后 D-01 立即归零（跨接口一致性）。"""
    _cleared(client, rich_user["header"], rich_user["password"])
    resp = client.get("/api/v1/me/data/summary", headers=rich_user["header"])
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["total_records"] == 0
    assert data["by_metric"] == []
    assert data["goals"] == {"active_count": 0, "paused_count": 0}
    assert data["profile"] == {"health_fields_filled": 0, "health_fields_total": 6}


# ════════════════════════════════════════════════════════════════════
# 越权隔离（**只清自己的**）
# ════════════════════════════════════════════════════════════════════
def test_d02_peer_data_untouched(client, rich_user, peer):
    """清空本端**不影响**对端任何数据。"""
    add_record(client, peer["header"], metric_type="weight", value_1="60.00",
               recorded_at=ts_before(days=1))
    add_goal(peer["user_id"], goal_type="water", status=1)

    _cleared(client, rich_user["header"], rich_user["password"])

    active_peer = _active_records(peer["user_id"])
    assert len(active_peer) == 1 and active_peer[0]["metric_type"] == "weight"
    active_goals = [g for g in goal_rows(peer["user_id"]) if g["is_deleted"] == 0]
    assert len(active_goals) == 1 and active_goals[0]["deleted_marker"] == 0


def test_d02_peer_token_cannot_clear_others(client, rich_user, peer):
    """对端用自己的 Token 调用 → 只清对端自己的数据（本端数据不变）。"""
    resp = clear(client, peer["header"], **confirm_payload(peer["password"]))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["deleted_records"] == 0

    assert len(_active_records(rich_user["user_id"])) == RICH_ACTIVE_RECORDS


def test_d02_rejects_user_id_in_body(client, rich_user, peer):
    """请求体携带 ``user_id`` → ``400 INVALID_PARAM``（且未清空任何数据）。"""
    payload = confirm_payload(rich_user["password"])
    payload["user_id"] = peer["user_id"]
    resp = clear(client, rich_user["header"], **payload)
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"
    assert len(_active_records(rich_user["user_id"])) == RICH_ACTIVE_RECORDS


# ════════════════════════════════════════════════════════════════════
# 禁止范围扩展参数
# ════════════════════════════════════════════════════════════════════
def test_d02_extra_params_have_no_effect(client, rich_user):
    """``include_profile_row`` / ``delete_account`` 等契约未定义参数**无任何效果**。"""
    resp = clear(client, rich_user["header"], **confirm_payload(
        rich_user["password"], include_profile_row=True, delete_account=True,
        include_sessions=True, force=True,
    ))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]

    assert data["scope"] == SCOPE                            # 范围未被扩大
    assert data["account_kept"] is True
    assert account_row(rich_user["user_id"]) is not None     # 账号仍在
    assert profile_row(rich_user["user_id"]) is not None     # 档案行仍在
    assert session_rows(rich_user["user_id"])                # 会话仍在


def test_d02_unknown_body_keys_ignored(client, rich_user):
    """未知键不报错、不改变范围（契约未定义 → 无效）。"""
    resp = clear(client, rich_user["header"], **confirm_payload(
        rich_user["password"], totally_unknown_key="x"))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["scope"] == SCOPE


# ════════════════════════════════════════════════════════════════════
# 事务失败 → 整体回滚
# ════════════════════════════════════════════════════════════════════
def test_d02_transaction_rolls_back_on_failure(client, rich_user, monkeypatch):
    """单事务：任一步失败 → **整体回滚**（不得出现「清一半」）+ ``500 INTERNAL_ERROR``。"""
    from app.services import data_service

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected-failure-for-rollback-test")

    monkeypatch.setattr(data_service, "_soft_delete_goals", _boom)

    resp = clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))
    assert resp.status_code == 500, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "INTERNAL_ERROR"
    assert "injected" not in resp.get_data(as_text=True)
    assert "injected" not in str(body)

    # 排他校验：记录 / 标签 / 档案 **均未** 被改动（前面已 pending 的软删被回滚）
    records = record_rows(rich_user["user_id"])
    assert [r["is_deleted"] for r in records] == [0, 0, 0, 1]
    assert all(r["deleted_at"] is None for r in records if r["is_deleted"] == 0)
    assert [t["is_deleted"] for t in tag_rows(rich_user["user_id"])] == [0, 0]
    assert profile_row(rich_user["user_id"])["height_cm"] is not None
    assert [g["deleted_marker"] for g in goal_rows(rich_user["user_id"])] == [0, 0]


def test_d02_recovers_after_rollback(client, rich_user, monkeypatch):
    """回滚后连接**未被污染**：撤销注入后同一账号可正常清空。"""
    from app.services import data_service

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(data_service, "_soft_delete_goals", _boom)
    assert clear(client, rich_user["header"],
                 **confirm_payload(rich_user["password"])).status_code == 500

    monkeypatch.undo()          # 撤销注入，恢复正常实现

    resp = clear(client, rich_user["header"], **confirm_payload(rich_user["password"]))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["deleted_records"] == 3
