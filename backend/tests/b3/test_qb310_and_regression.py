# -*- coding: utf-8 -*-
"""B3 · Q-B3-10（找回成功后清零登录失败状态）＋ 自助找回链路闭合回归。

覆盖需求方 B3 授权 §六（``Q-B3-10`` 前置只读确认与最小实现）与 §八 的
「未验证邮箱 PR-01 不发送 / 已验证邮箱 PR-01 可进入发送链」用例：

| # | 用例 |
|---|---|
| 1 | 找回成功后 ``login_failure_state`` **被清零**（复用登录成功语义） |
| 2 | 找回成功后**可正常登录**（不再被 423 ``ACCOUNT_LOCKED`` 挡住） |
| 3 | 无失败状态行时**不新建**（不污染 ``login_failure_state``） |
| 4 | 清零**只作用于本账号**（不越界影响他人） |
| 5 | 未绑定邮箱 ⇒ PR-01 恒等响应且**不发送** |
| 6 | 已验证邮箱 ⇒ PR-01 **进入发送链**（此前是断链，B3 补齐） |
| 7 | **端到端闭环**：绑定邮箱 → PR-01 → PR-02 → PR-03 → 用新密码登录 |
| 8 | 回归：``DELETE_ORDER`` 仍为 10 项且包含两张安全表（B3 未改 A-07） |
"""
from __future__ import annotations

from app.services.account_service import DELETE_ORDER
from app.services import mail_service

from tests.b3.conftest import (
    DEFAULT_PASSWORD,
    NEW_PASSWORD,
    access_token_of,
    bind_email_via_api,
    failure_state_of,
    latest_reset_code_for,
    login,
    obtain_reset_token,
    one,
    register_token,
    req_confirm,
    req_reset,
    unique_email,
)


def _lock_account_by_wrong_logins(client, username: str, cap: int = 12) -> None:
    """用错误密码登录直到触发锁定（``423 ACCOUNT_LOCKED``）。"""
    for _ in range(cap):
        resp = login(client, username, "wrongpass1")
        if resp.status_code == 423:
            return
        assert resp.status_code == 401, resp.get_data(as_text=True)
    raise AssertionError("未能在限定次数内触发账号锁定")


# ══════════════════════════════════════════════════════════════════
# 1-2. Q-B3-10：找回成功后清零失败状态，且可正常登录
# ══════════════════════════════════════════════════════════════════
def test_qb310_reset_clears_login_failure_state(client):
    username, uid, token = register_token(client)
    email = unique_email("lock")
    bind_email_via_api(client, token, email)  # 先让找回链路可发信

    _lock_account_by_wrong_logins(client, username)
    before = failure_state_of(username)
    assert before is not None and before["locked_until"] is not None
    assert before["lock_level"] >= 1

    # 完整走找回：PR-01 → PR-02 → PR-03
    reset_token = obtain_reset_token(client, username, email)
    assert req_confirm(client, reset_token, new_password=NEW_PASSWORD).status_code == 200

    # ★ 失败状态被清零（行仍在，但计数 / 锁定 / 档位归零）
    after = failure_state_of(username)
    assert after is not None, "不应删除该行（只清零）"
    assert after["fail_count"] == 0
    assert after["lock_level"] == 0
    assert after["locked_until"] is None
    assert after["first_fail_at"] is None

    # ★ 用户现在能正常登录（不再被 423 挡住）——Q-B3-10 的真实价值
    ok = login(client, username, NEW_PASSWORD)
    assert ok.status_code == 200, ok.get_data(as_text=True)
    # 旧密码失效（PR-03 确已生效）
    assert login(client, username, DEFAULT_PASSWORD).status_code == 401


# ══════════════════════════════════════════════════════════════════
# 3. 无失败状态行 ⇒ 不新建（不污染 login_failure_state）
# ══════════════════════════════════════════════════════════════════
def test_qb310_absent_state_is_not_created(client):
    username, uid, token = register_token(client)
    email = unique_email("nostate")
    bind_email_via_api(client, token, email)
    assert failure_state_of(username) is None  # 注册 / 绑定都不落失败状态行

    reset_token = obtain_reset_token(client, username, email)
    assert req_confirm(client, reset_token, new_password=NEW_PASSWORD).status_code == 200

    # 最小实现：无行则不创建
    assert failure_state_of(username) is None, "Q-B3-10 不得为无失败记录的账号新建状态行"


# ══════════════════════════════════════════════════════════════════
# 4. 清零只作用于本账号
# ══════════════════════════════════════════════════════════════════
def test_qb310_reset_is_scoped_to_own_account(client):
    user_a, uid_a, token_a = register_token(client)
    user_b, uid_b, token_b = register_token(client)
    email_a = unique_email("scopeda")
    bind_email_via_api(client, token_a, email_a)

    _lock_account_by_wrong_logins(client, user_b)
    b_before = failure_state_of(user_b)
    assert b_before is not None and b_before["locked_until"] is not None

    reset_token = obtain_reset_token(client, user_a, email_a)
    assert req_confirm(client, reset_token, new_password=NEW_PASSWORD).status_code == 200

    # B 的失败状态**原样保留**
    b_after = failure_state_of(user_b)
    assert b_after is not None
    assert b_after["locked_until"] == b_before["locked_until"]
    assert b_after["lock_level"] == b_before["lock_level"]


# ══════════════════════════════════════════════════════════════════
# 5. 未绑定邮箱 ⇒ PR-01 恒等响应且不发送
# ══════════════════════════════════════════════════════════════════
def test_pr01_unbound_email_does_not_send(client):
    username, uid = register_token(client)[:2]
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None

    resp = req_reset(client, username)
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "如果该账号存在且已绑定邮箱，我们已发送验证码"
    assert resp.get_json()["data"] is None
    assert mail_service.memory_outbox() == []
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 0


# ══════════════════════════════════════════════════════════════════
# 6. 已验证邮箱 ⇒ PR-01 进入发送链（B3 补齐的断点）
# ══════════════════════════════════════════════════════════════════
def test_pr01_verified_email_enters_send_chain(client):
    username, uid, token = register_token(client)
    email = unique_email("chain")
    assert mail_service.memory_outbox() == []

    bind_email_via_api(client, token, email)
    assert one("SELECT email_verified_at IS NOT NULL FROM user_account WHERE id=:u", u=uid) == 1

    resp = req_reset(client, username)
    assert resp.status_code == 200  # **仍是**恒等响应（防枚举不受影响）
    # ⚠️ 判据自纠（铁律②「改判据不改产品代码」）：内存投递箱里**已含**上一步
    #    「绑定邮箱」时发出的 email_bind 邮件 ⇒ 必须**按 purpose 过滤**后再计数，
    #    否则会把 1 封 email_bind ＋ 1 封 password_reset 误判为「多发了一封」而假 FAIL。
    reset_box = [i for i in mail_service.memory_outbox() if i.get("purpose") == "password_reset"]
    assert len(reset_box) == 1
    assert reset_box[0]["to"] == email
    assert latest_reset_code_for(email) is not None
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND purpose='password_reset'",
        u=uid,
    ) == 1


# ══════════════════════════════════════════════════════════════════
# 7. 端到端闭环：绑定 → 找回 → 新密码登录
# ══════════════════════════════════════════════════════════════════
def test_end_to_end_bind_then_selfservice_reset(client):
    username, uid, token = register_token(client)
    email = unique_email("e2e")

    # ① B3 新增能力：绑定已验证邮箱（这是此前缺失的唯一断点）
    bind_email_via_api(client, token, email)

    # ② 自助找回全链路
    reset_token = obtain_reset_token(client, username, email)
    confirm = req_confirm(client, reset_token, new_password=NEW_PASSWORD)
    assert confirm.status_code == 200, confirm.get_data(as_text=True)
    assert confirm.get_json()["data"]["all_sessions_revoked"] is True

    # ③ 新密码可登录、旧密码失效、原会话已撤销
    assert login(client, username, NEW_PASSWORD).status_code == 200
    assert login(client, username, DEFAULT_PASSWORD).status_code == 401
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_at IS NULL "
        "AND revoked_reason IS NULL",
        u=uid,
    ) == 1  # 仅剩本次「新密码登录」新建的那条
    assert one(
        "SELECT COUNT(*) FROM user_session WHERE user_id=:u AND revoked_reason='password_reset'",
        u=uid,
    ) >= 1


# ══════════════════════════════════════════════════════════════════
# 8. 回归：B3 未改动 A-07 的删除顺序
# ══════════════════════════════════════════════════════════════════
def test_delete_order_unchanged_by_b3():
    assert len(DELETE_ORDER) == 10, DELETE_ORDER
    assert DELETE_ORDER[-1] == "user_account"
    assert {"verification_code", "password_reset_token"} <= set(DELETE_ORDER)
    # 与 B2 封板值逐字一致（B3 未新增任何表 ⇒ 顺序不得变）
    assert DELETE_ORDER == (
        "record_tag",
        "health_record",
        "health_goal",
        "user_profile",
        "export_job",
        "user_session",
        "login_failure_state",
        "verification_code",
        "password_reset_token",
        "user_account",
    )
