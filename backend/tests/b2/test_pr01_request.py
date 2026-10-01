# -*- coding: utf-8 -*-
"""B2 · PR-01 请求密码找回（``POST /api/v1/auth/password-reset/request``）。

覆盖需求方 §十二「PR-01」6 项：
存在＋已验证邮箱 / 不存在账号 / 未绑定邮箱 / **统一响应防枚举** /
新码使旧码失效 / code 不明文入库 / 日志不泄漏。
外加 §五.7 冻结的**重发冷却**（60 秒）行为。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import text

from app.core.db import get_engine
from app.core.password_reset import CODE_TTL_MINUTES, RESEND_COOLDOWN_SECONDS
from app.services import mail_service

from tests.b2.conftest import (
    API,
    latest_code_for,
    one,
    register_with_email,
    register_account,
    req_reset,
    req_verify,
    exec_sql,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _body(resp) -> dict:
    return resp.get_json()


def _core(body: dict) -> dict:
    """剔除 ``request_id`` 后的可比对响应（request_id 每次必然不同）。"""
    return {k: v for k, v in body.items() if k != "request_id"}


# ══════════════════════════════════════════════════════════════════
# 1. 存在 + 已验证邮箱 ⇒ 真正生成验证码并投递
# ══════════════════════════════════════════════════════════════════
def test_request_with_verified_email_creates_code_and_delivers(client):
    username, uid, email = register_with_email(client)

    resp = req_reset(client, username)
    assert resp.status_code == 200
    body = _body(resp)
    assert body["code"] == "OK"
    assert body["data"] is None
    assert body["message"] == "如果该账号存在且已绑定邮箱，我们已发送验证码"

    # DB：恰 1 行挑战记录；purpose 正确；未消费
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND purpose='password_reset'",
        u=uid,
    ) == 1
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 1
    # TTL 与冻结常量一致
    delta = one(
        "SELECT TIMESTAMPDIFF(MINUTE, created_at, expires_at) FROM verification_code "
        "WHERE user_id=:u ORDER BY id DESC LIMIT 1",
        u=uid,
    )
    assert int(delta) == CODE_TTL_MINUTES

    # 投递载荷：恰 1 封，收件人＝绑定邮箱
    box = mail_service.memory_outbox()
    assert len(box) == 1
    assert box[0]["to"] == email
    assert latest_code_for(email) is not None


# ══════════════════════════════════════════════════════════════════
# 2. 不存在账号 ⇒ 恒等响应，且**不产生任何码 / 邮件**
# ══════════════════════════════════════════════════════════════════
def test_request_unknown_account_is_indistinguishable(client):
    resp = req_reset(client, "nosuchuserzzz9")
    assert resp.status_code == 200
    body = _body(resp)
    assert body["code"] == "OK"
    assert body["data"] is None
    assert body["message"] == "如果该账号存在且已绑定邮箱，我们已发送验证码"
    assert mail_service.memory_outbox() == []
    assert one("SELECT COUNT(*) FROM verification_code") == 0


# ══════════════════════════════════════════════════════════════════
# 3. 未绑定邮箱 ⇒ 恒等响应，且不产生码 / 邮件
# ══════════════════════════════════════════════════════════════════
def test_request_without_email_is_indistinguishable(client):
    username, uid = register_account(client)  # 不绑邮箱
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) is None

    resp = req_reset(client, username)
    assert resp.status_code == 200
    assert _body(resp)["data"] is None
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 0
    assert mail_service.memory_outbox() == []


# ══════════════════════════════════════════════════════════════════
# 4. 三态（命中 / 不存在 / 未绑定）响应逐字一致
# ══════════════════════════════════════════════════════════════════
def test_request_three_states_share_identical_envelope(client):
    username, uid, email = register_with_email(client)
    plain_username, _ = register_account(client)  # 未绑定邮箱

    hit = req_reset(client, username)
    missing = req_reset(client, "nosuchuserzzz9")
    unbound = req_reset(client, plain_username)

    assert hit.status_code == missing.status_code == unbound.status_code == 200
    assert _core(_body(hit)) == _core(_body(missing)) == _core(_body(unbound))
    # 响应中**绝不**回显邮箱（即便掩码）
    assert email not in hit.get_data(as_text=True)


# ══════════════════════════════════════════════════════════════════
# 5. 冷却期内重发 ⇒ 仍 200 恒等，但**不签发新码**（Q-PR-5 冻结：统一 200 不发信）
# ══════════════════════════════════════════════════════════════════
def test_resend_within_cooldown_issues_no_new_code(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    first_hash = one(
        "SELECT code_hash FROM verification_code WHERE user_id=:u ORDER BY id DESC LIMIT 1", u=uid
    )

    again = req_reset(client, username)
    assert again.status_code == 200
    assert _core(_body(again)) == {
        "code": "OK",
        "message": "如果该账号存在且已绑定邮箱，我们已发送验证码",
        "data": None,
    }
    # 码数未增、哈希未变、邮件未多
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 1
    assert one(
        "SELECT code_hash FROM verification_code WHERE user_id=:u", u=uid
    ) == first_hash
    assert len(mail_service.memory_outbox()) == 1


# ══════════════════════════════════════════════════════════════════
# 6. 签发新码 ⇒ 旧码立即失效（CODE_MAX_ACTIVE_PER_PURPOSE = 1）
# ══════════════════════════════════════════════════════════════════
def test_new_code_invalidates_previous_code(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    old_code = latest_code_for(email)
    old_hash = one(
        "SELECT code_hash FROM verification_code WHERE user_id=:u ORDER BY id DESC LIMIT 1", u=uid
    )

    # 绕过 60 秒冷却（把上一条的 created_at 提前到 2 分钟前）
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u",
        u=uid,
    )
    req_reset(client, username)

    # 共 2 行：旧的已 consumed，新的未 consumed
    assert one("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid) == 2
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL", u=uid
    ) == 1
    assert one(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND code_hash=:h", u=uid, h=old_hash
    ) == 1
    assert one(
        "SELECT consumed_at IS NOT NULL FROM verification_code WHERE code_hash=:h", h=old_hash
    ) == 1

    # 旧码在 PR-02 已不可用（统一 422）
    old_try = req_verify(client, username, old_code)
    assert old_try.status_code == 422
    assert old_try.get_json()["message"] == "请确认是否输错"
    assert old_try.get_json()["errors"][0]["message"] == "验证码不正确或已过期"


# ══════════════════════════════════════════════════════════════════
# 7. 验证码**绝不**明文入库（结构上无明文列 + 实测无 6 位明文）
# ══════════════════════════════════════════════════════════════════
def test_verification_code_never_stored_in_plaintext(client):
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    code = latest_code_for(email)
    assert code is not None and len(code) == 6 and code.isdigit()

    with get_engine().connect() as conn:
        cols = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='verification_code'"
                )
            ).all()
        ]
        # ① 结构上**没有**任何可存明文的列
        assert "code" not in cols, "verification_code 出现了明文列"
        assert "code_hash" in cols
        # ② 全列扫描：**没有任何列的值**等于本次投递的明文码
        for col in cols:
            # ⚠️ 必须 CAST 成字符串再比较：目标表含 DATETIME 列
            #    （created_at / expires_at / consumed_at），把 6 位码直接绑给
            #    DATETIME 会被 MySQL 判为非法值（错误 1525）—— 那是**判据缺陷**，
            #    不是产品缺陷。
            hit = int(
                conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM verification_code "
                        f"WHERE CAST(`{col}` AS CHAR) = :c"
                    ),
                    {"c": code},
                ).scalar()
                or 0
            )
            assert hit == 0, f"列 {col} 中出现了验证码明文"
        # ③ 落库哈希形态正确，且不等于明文
        code_hash, purpose, attempt_count, consumed_at = conn.execute(
            text(
                "SELECT code_hash, purpose, attempt_count, consumed_at FROM verification_code "
                "WHERE user_id=:u"
            ),
            {"u": uid},
        ).all()[0]
    assert HEX64.match(str(code_hash))
    assert str(code_hash) != code
    assert purpose == "password_reset"
    assert int(attempt_count) == 0
    assert consumed_at is None


# ══════════════════════════════════════════════════════════════════
# 8. 日志**不泄漏** username / email / code
# ══════════════════════════════════════════════════════════════════
def test_logging_does_not_leak_code_or_email(client, app, caplog):
    """日志不泄漏邮箱 / 验证码。

    ⚠️ 判据加强（B2 自纠）：**以 pytest 捕获的原始 LogRecord 为主判据**。
    主判据不经 handler 的 ``SensitiveDataFilter`` ⇒ 证明的是「**根本没有把**
    **真值拼进日志消息**」，强于「过滤后没落盘」；且**不依赖文件 handler 是否健康**
    （本机 2026-09-24 起 ``app.log`` 被外部进程占用 → 轮转失败 → 文件 logger 静默
    失效；若只以文件内容为判据会**空转通过**）。
    """
    with caplog.at_level(logging.INFO):
        username, uid, email = register_with_email(client)
        req_reset(client, username)
        code = latest_code_for(email)
    assert code is not None and len(code) == 6 and code.isdigit()

    raw = caplog.text
    assert raw.strip() != "", "未捕获到任何日志记录 ⇒ 判据会空转通过"
    # 邮箱 / 用户名是长随机串，直接子串判定安全
    assert email not in raw, "日志记录出现邮箱明文"
    assert f"username={username}" not in raw, "日志记录出现用户名字段明文"
    # 6 位数字码可能与耗时/request_id 偶然重合 ⇒ 用**键值形态**判据
    for pattern in (
        f"code={code}",
        f"'code': '{code}'",
        f'"code": "{code}"',
        f"code='{code}'",
        f'code="{code}"',
    ):
        assert pattern not in raw, f"日志以字段形态出现验证码明文：{pattern}"

    # 附加（环境相关）：若文件 handler 正常落盘，则整个文件同样不得出现该邮箱
    log_path = Path(app.config["LOG_DIR"]) / "app.log"
    if log_path.exists():
        fresh = log_path.read_text(encoding="utf-8", errors="replace")
        assert email not in fresh, "日志文件出现邮箱明文"


# ══════════════════════════════════════════════════════════════════
# 9. 契约边界：body 非 JSON / 缺 username ⇒ 400；带 user_id ⇒ 400（全局守卫）
# ══════════════════════════════════════════════════════════════════
def test_request_contract_rejects_bad_body(client):
    no_json = client.post(f"{API}/auth/password-reset/request", data="x")
    assert no_json.status_code == 400
    assert no_json.get_json()["code"] == "INVALID_PARAM"

    empty = client.post(f"{API}/auth/password-reset/request", json={})
    assert empty.status_code == 400
    assert empty.get_json()["code"] == "INVALID_PARAM"
    assert empty.get_json()["errors"][0]["field"] == "username"

    # 「不得临时输入新邮箱」：email 是未知字段 ⇒ EXCLUDE，不进任何逻辑
    sneaky = client.post(
        f"{API}/auth/password-reset/request",
        json={"username": "nosuchuserzzz9", "email": "attacker@evil.com"},
    )
    assert sneaky.status_code == 200
    assert mail_service.memory_outbox() == []

    # user_id 出现在请求体 ⇒ 全局身份守卫 400
    with_uid = client.post(
        f"{API}/auth/password-reset/request", json={"username": "x", "user_id": 1}
    )
    assert with_uid.status_code == 400
    assert with_uid.get_json()["code"] == "INVALID_PARAM"


# ══════════════════════════════════════════════════════════════════
# 10. 冷却是服务端行为（不依赖前端）
# ══════════════════════════════════════════════════════════════════
def test_cooldown_threshold_is_server_side(client):
    """冷却窗口常量应来自冻结常量（60s），且重置 created_at 后可再发。"""
    assert RESEND_COOLDOWN_SECONDS == 60
    username, uid, email = register_with_email(client)
    req_reset(client, username)
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL :s SECOND) "
        "WHERE user_id=:u",
        s=RESEND_COOLDOWN_SECONDS + 5,
        u=uid,
    )
    req_reset(client, username)
    assert len(mail_service.memory_outbox()) == 2
