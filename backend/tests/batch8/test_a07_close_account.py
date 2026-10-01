# -*- coding: utf-8 -*-
"""S2 第八批 A-07（``DELETE /api/v1/users/me`` 注销账号）—— 核心验收用例。

覆盖：
A 正常注销 · B 无 Token / 坏 Token · C 密码错误且账号数据保持完整 · D 确认文字缺失/错误 ·
E 只能注销当前账号 · F access / refresh Token 全部失效 · G 已软删 ``health_record`` 也物理删除 ·
H ``user_profile`` 整行删除 · I ``export_job`` 删除 · J ``record_tag`` / ``health_goal`` 含软删数据全删 ·
L 注销后账号不存在 · M 用户名可重新注册 · N 第二测试账号完全不受影响；
另覆盖：请求体 ``user_id`` 被现有守卫拦截 · 不支持 ``target_user_id`` / ``force`` / ``grace_period`` /
``defer`` / ``schedule`` · ``login_failure_state`` 按 ``username`` 清除 · 重复注销 401 ·
envelope 与错误码契约 · **A-07 与 D-02 文案严格区分**。

★ 全部用例**只**操作 ``tst`` 独立测试账号；不对任何非测试账号执行注销。
"""
from __future__ import annotations

from tests.batch8.conftest import (
    API,
    CONFIRM_TEXT,
    account_by_username,
    account_row,
    add_goal,
    close_account,
    close_payload,
    goal_rows,
    job_rows,
    login_failure_rows,
    make_user,
    profile_row,
    record_rows,
    session_rows,
    tag_rows,
)


def _closed(client, header, password, **overrides):
    """执行合法注销并返回响应体（断言 200）。"""
    resp = close_account(client, header, **close_payload(password, **overrides))
    assert resp.status_code == 200, (resp.status_code, resp.get_json())
    return resp.get_json()


# ════════════════════════════════════════════════════════════════════
# B 鉴权
# ════════════════════════════════════════════════════════════════════
def test_a07_requires_auth(client):
    """无 Token → ``401 UNAUTHENTICATED``（**不得**因缺参先返回 400/422）。"""
    resp = client.delete(f"{API}/users/me", json=close_payload())
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"
    assert resp.get_json()["data"] is None


def test_a07_bad_token(client):
    resp = client.delete(f"{API}/users/me",
                         headers={"Authorization": "Bearer not-a-token"},
                         json=close_payload())
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_a07_no_body_is_invalid_param(client, user):
    """无请求体 → ``400 INVALID_PARAM``（数据未变）。"""
    resp = client.delete(f"{API}/users/me", headers=user["header"])
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"
    assert account_row(user["user_id"]) is not None


# ════════════════════════════════════════════════════════════════════
# D 确认文字（``confirm_text`` 必须是「注销账号」）
# ════════════════════════════════════════════════════════════════════
def test_a07_confirm_text_missing(client, user):
    resp = close_account(client, user["header"], password=user["password"])
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["errors"][0]["field"] == "confirm_text"
    assert body["errors"][0]["code"] == "REQUIRED"
    assert account_row(user["user_id"]) is not None


def test_a07_confirm_text_wrong(client, user):
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], confirm_text="注销"))
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["errors"][0]["field"] == "confirm_text"
    assert body["errors"][0]["code"] == "INVALID_FORMAT"
    assert account_row(user["user_id"]) is not None


def test_a07_d02_confirm_text_is_rejected(client, user):
    """**A-07 与 D-02 文案严格区分**：D-02 的「确认删除」不得用于注销。"""
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], confirm_text="确认删除"))
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["errors"][0]["field"] == "confirm_text"
    assert account_row(user["user_id"]) is not None


def test_a07_confirm_text_empty(client, user):
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], confirm_text="   "))
    assert resp.status_code == 422, resp.get_json()
    assert account_row(user["user_id"]) is not None


def test_a07_confirm_checked_before_password(client, user):
    """确认文字错误 + 密码错误 → 断言**确认文字**错误（校验顺序：确认 → 密码）。"""
    resp = close_account(client, user["header"],
                         **close_payload("wrong-pass-1", confirm_text="错的"))
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["errors"][0]["field"] == "confirm_text"


# ════════════════════════════════════════════════════════════════════
# C 密码
# ════════════════════════════════════════════════════════════════════
def test_a07_password_missing(client, user):
    resp = close_account(client, user["header"], confirm_text=CONFIRM_TEXT)
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["errors"][0]["field"] == "password"
    assert body["errors"][0]["code"] == "REQUIRED"
    assert account_row(user["user_id"]) is not None


def test_a07_password_empty(client, user):
    resp = close_account(client, user["header"], **close_payload(password="   "))
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["errors"][0]["field"] == "password"


def test_a07_password_wrong_keeps_account_and_data_intact(client, rich_user):
    """★ C：密码错误 → ``422 PASSWORD_INVALID``，**账号与 8 张表数据全部保持原状**。"""
    uid = rich_user["user_id"]
    before = {
        "records": len(record_rows(uid)),
        "tags": len(tag_rows(uid)),
        "goals": len(goal_rows(uid)),
        "profile": profile_row(uid),
        "jobs": len(job_rows(uid)),
        "sessions": len(session_rows(uid)),
        "fail": len(login_failure_rows(rich_user["username"])),
    }
    resp = close_account(client, rich_user["header"],
                         **close_payload("wrong-pass-9"))
    assert resp.status_code == 422, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "PASSWORD_INVALID", body
    assert body["data"] is None
    # 数据未变
    assert account_row(uid) is not None
    assert len(record_rows(uid)) == before["records"]
    assert len(tag_rows(uid)) == before["tags"]
    assert len(goal_rows(uid)) == before["goals"]
    assert profile_row(uid) == before["profile"]
    assert len(job_rows(uid)) == before["jobs"]
    assert len(session_rows(uid)) == before["sessions"]
    assert len(login_failure_rows(rich_user["username"])) == before["fail"]


def test_a07_wrong_password_never_counts_and_never_429(client, user):
    """密码连错 5 次：**全部 422 PASSWORD_INVALID**，无 429、无锁定、无失败计数。"""
    uid = user["user_id"]
    for _ in range(5):
        resp = close_account(client, user["header"], **close_payload("wrong-pass-7"))
        assert resp.status_code == 422, resp.get_json()
        assert resp.get_json()["code"] == "PASSWORD_INVALID"
    assert account_row(uid) is not None
    assert login_failure_rows(user["username"]) == []
    assert session_rows(uid), "会话不得因密码错误被移除"
    for row in session_rows(uid):
        assert row["export_pwd_fail_count"] == 0
        assert row["change_pwd_fail_count"] == 0


def test_a07_can_login_after_wrong_password_attempts(client, user):
    """密码错多次后仍可正常登录（证明未触发任何锁定）。"""
    for _ in range(3):
        close_account(client, user["header"], **close_payload("wrong-pass-3"))
    resp = client.post(f"{API}/auth/login",
                       json={"username": user["username"], "password": user["password"]})
    assert resp.status_code == 200, resp.get_json()


# ════════════════════════════════════════════════════════════════════
# A / L 正常注销 + 账号不存在
# ════════════════════════════════════════════════════════════════════
def test_a07_success_shape_and_message(client, user):
    """A：成功 → ``200`` + ``message="账号已注销"`` + ``data`` **恰 1 键**。"""
    body = _closed(client, user["header"], user["password"])
    assert body["code"] == "OK"
    assert body["message"] == "账号已注销"
    assert body["data"] == {"account_closed": True}
    assert set(body["data"].keys()) == {"account_closed"}
    assert set(body.keys()) == {"code", "message", "data", "request_id"}


def test_a07_success_purges_all_eight_tables(client, rich_user):
    """★ 正常注销：8 张表中该账号数据**全部物理清零**。"""
    uid = rich_user["user_id"]
    # 前置：8 张表都确实有该账号的数据
    assert account_row(uid) is not None
    assert profile_row(uid) is not None
    assert record_rows(uid)
    assert tag_rows(uid)
    assert goal_rows(uid)
    assert session_rows(uid)
    assert login_failure_rows(rich_user["username"])
    assert job_rows(uid)

    _closed(client, rich_user["header"], rich_user["password"])

    assert account_row(uid) is None
    assert account_by_username(rich_user["username"]) is None
    assert profile_row(uid) is None
    assert record_rows(uid) == []
    assert tag_rows(uid) == []
    assert goal_rows(uid) == []
    assert session_rows(uid) == []
    assert login_failure_rows(rich_user["username"]) == []
    assert job_rows(uid) == []


def test_a07_soft_deleted_rows_are_purged_too(client, rich_user):
    """★ G + J：**已软删**的 ``health_record`` / ``health_goal`` **不等 30 天，一并物理删除**。"""
    uid = rich_user["user_id"]
    assert any(r["is_deleted"] == 1 for r in record_rows(uid)), "前置：存在软删记录"
    assert any(r["is_deleted"] == 1 for r in goal_rows(uid)), "前置：存在软删目标"

    _closed(client, rich_user["header"], rich_user["password"])

    assert record_rows(uid) == []
    assert goal_rows(uid) == []
    assert tag_rows(uid) == []


def test_a07_profile_row_is_removed_entirely(client, rich_user):
    """★ H：``user_profile`` **整行删除**（不是 D-02 的"仅清空健康字段"）。"""
    uid = rich_user["user_id"]
    row = profile_row(uid)
    assert row is not None and row["nickname"] == "测试昵称"
    _closed(client, rich_user["header"], rich_user["password"])
    assert profile_row(uid) is None


def test_a07_export_job_removed(client, rich_user):
    """★ I（数据库侧）：``export_job`` 行物理删除。"""
    uid = rich_user["user_id"]
    assert job_rows(uid)
    _closed(client, rich_user["header"], rich_user["password"])
    assert job_rows(uid) == []


def test_a07_login_failure_state_cleared_by_username(client, rich_user):
    """``login_failure_state`` **按 ``username``** 物理删除。"""
    assert login_failure_rows(rich_user["username"])
    _closed(client, rich_user["header"], rich_user["password"])
    assert login_failure_rows(rich_user["username"]) == []


def test_a07_all_sessions_removed(client, rich_user):
    """★ F：``user_session`` **全部**物理删除（含额外设备会话）。"""
    uid = rich_user["user_id"]
    assert len(session_rows(uid)) >= 2
    _closed(client, rich_user["header"], rich_user["password"])
    assert session_rows(uid) == []


# ════════════════════════════════════════════════════════════════════
# F Token / 幂等
# ════════════════════════════════════════════════════════════════════
def test_a07_old_access_token_rejected_after_close(client, user):
    """F：注销后原 Access Token **立即失效** → ``401``。"""
    _closed(client, user["header"], user["password"])
    resp = client.get(f"{API}/users/me", headers=user["header"])
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_a07_refresh_token_rejected_after_close(client, user):
    """F：注销后原 Refresh Token 亦失效（会话行已删除）→ ``401``。"""
    refresh = user.get("refresh_token")
    assert refresh, "前置：注册应返回 refresh_token"
    _closed(client, user["header"], user["password"])
    resp = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401, resp.get_json()


def test_a07_repeat_close_returns_401(client, user):
    """幂等：**重复提交注销** → ``401``（Token 已失效，天然幂等）。"""
    _closed(client, user["header"], user["password"])
    resp = close_account(client, user["header"], **close_payload(user["password"]))
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_a07_protected_endpoints_unreachable_after_close(client, user):
    """注销后原 Token 访问任何受保护接口均为 401。"""
    _closed(client, user["header"], user["password"])
    for path in ("/api/v1/users/me", "/api/v1/profile",
                 "/api/v1/records", "/api/v1/goals",
                 "/api/v1/me/data/summary"):
        resp = client.get(f"{API}{path.replace('/api/v1', '')}", headers=user["header"])
        assert resp.status_code == 401, (path, resp.status_code)


# ════════════════════════════════════════════════════════════════════
# M 用户名释放
# ════════════════════════════════════════════════════════════════════
def test_a07_username_released_and_reusable(client, user):
    """★ M：账号物理删除后**用户名释放**，可被再次注册。"""
    _closed(client, user["header"], user["password"])
    resp = client.post(f"{API}/auth/register", json={
        "username": user["username"],
        "password": user["password"],
        "agreement_version": "v1.0",
        "agreement_accepted": True,
    })
    assert resp.status_code == 201, resp.get_json()


# ════════════════════════════════════════════════════════════════════
# E / N 隔离
# ════════════════════════════════════════════════════════════════════
def test_a07_peer_account_untouched(client, user, peer):
    """★ N：注销 A 后，B 账号的账号行 / 会话 / 档案**完全不受影响**。"""
    peer_uid = peer["user_id"]
    peer_sessions = len(session_rows(peer_uid))
    _closed(client, user["header"], user["password"])
    assert account_row(peer_uid) is not None
    assert len(session_rows(peer_uid)) == peer_sessions
    resp = client.get(f"{API}/users/me", headers=peer["header"])
    assert resp.status_code == 200, resp.get_json()


def test_a07_peer_token_cannot_close_others(client, user, peer):
    """★ E：B 的 Token 只能注销 B 自己，**绝不删 A 的账号**。"""
    uid = user["user_id"]
    _closed(client, peer["header"], peer["password"])
    assert account_row(uid) is not None, "A 账号不得被 B 的请求删除"
    assert account_by_username(user["username"]) is not None
    assert account_row(peer["user_id"]) is None


def test_a07_peer_data_untouched(client, rich_user, peer):
    """rich_user 注销后，peer 的业务数据行数不变。"""
    peer_uid = peer["user_id"]
    add_goal(peer_uid, goal_type="water", status=1)
    before = (len(goal_rows(peer_uid)), len(record_rows(peer_uid)))
    _closed(client, rich_user["header"], rich_user["password"])
    after = (len(goal_rows(peer_uid)), len(record_rows(peer_uid)))
    assert after == before


# ════════════════════════════════════════════════════════════════════
# 参数边界
# ════════════════════════════════════════════════════════════════════
def test_a07_rejects_user_id_in_body(client, user):
    """请求体出现 ``user_id`` → 现有全局守卫 ``400 INVALID_PARAM``。"""
    resp = close_account(client, user["header"],
                         **close_payload(user["password"], user_id=999999))
    assert resp.status_code == 400, resp.get_json()
    assert resp.get_json()["code"] == "INVALID_PARAM"
    assert account_row(user["user_id"]) is not None


def test_a07_scope_expansion_params_have_no_effect(client, user, peer):
    """不支持 ``target_user_id`` / ``force`` / ``grace_period`` / ``defer`` / ``schedule``。

    这些参数**不得**扩大删除范围：只注销自己，**不触碰**目标账号。
    """
    peer_uid = peer["user_id"]
    body = _closed(
        client, user["header"], user["password"],
        target_user_id=peer_uid, force=True, grace_period=30,
        defer=True, schedule="later", include_profile_row=True,
        delete_account=False,
    )
    assert body["data"] == {"account_closed": True}
    assert account_row(user["user_id"]) is None            # 自己已注销
    assert account_row(peer_uid) is not None               # 对端毫发无损


def test_a07_client_time_ignored(client, user):
    """``client_time`` 仅用于排查，**不参与业务判定**（乱填也能成功）。"""
    body = _closed(client, user["header"], user["password"], client_time="not-a-date")
    assert body["message"] == "账号已注销"
    assert account_row(user["user_id"]) is None


def test_a07_acknowledge_irreversible_is_not_required(client, user):
    """C2 冻结：A-07 **不含** ``acknowledge_irreversible`` —— 缺省即可成功，传值也无效果。"""
    assert account_row(user["user_id"]) is not None
    body = _closed(client, user["header"], user["password"],
                   acknowledge_irreversible=False)
    assert body["data"] == {"account_closed": True}


def test_a07_unknown_body_keys_ignored(client, user):
    body = _closed(client, user["header"], user["password"], nonsense="x", extra=[1, 2])
    assert body["code"] == "OK"


def test_a07_payload_never_reads_user_id_from_token_only(client):
    """未登录 + 仅带 ``user_id`` → 401（守卫先于鉴权，或鉴权先于业务，均不得成功）。"""
    resp = client.delete(f"{API}/users/me", json=close_payload(user_id=1))
    assert resp.status_code in (400, 401), resp.get_json()
