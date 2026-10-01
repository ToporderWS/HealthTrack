# -*- coding: utf-8 -*-
"""B3 · 契约收口与安全边界（错误码 / 路由 / 日志脱敏 / purpose 隔离 / DB 不变量）。

覆盖需求方 B3 授权 §八 中偏「契约与安全」的用例：

| # | 用例 |
|---|---|
| 1 | ``EMAIL_TAKEN`` 契约：码值 / HTTP 409 / 中性文案（**add-only**） |
| 2 | 全局错误码总数 = 19（18 冻结 ＋ B3 追加 1） |
| 3 | 蓝图 ＋ 两条路由已注册（13 蓝图；POST；``/auth/email/bind-*``） |
| 4 | 两条端点**均需登录**（未登录 ⇒ 401） |
| 5 | 全链路日志**不含**邮箱 / 验证码明文（**原始 LogRecord** 判据） |
| 6 | ``code=OK`` 等正常业务字段**不得**被误脱敏 |
| 7 | 邮箱绑定邮件模板为**纯文本**且占位符被替换 |
| 8 | 内存投递箱**按 purpose 分类**（email_bind / password_reset 互不混淆） |
| 9 | HMAC 结构上绑定 **purpose** 与 **邮箱**（单元级） |
| 10 | **端到端 purpose 隔离**：两种码互不通用 |
| 11 | ``user_account`` 的 email 配对 CHECK 约束存在（「已填未验证」结构上不可能） |
| 12 | 实测错误码 ⊆ 冻结集合（无表外码） |
"""
from __future__ import annotations

import logging
import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.db import session_scope
from app.core.errors import ERROR_HTTP_STATUS, ERROR_MESSAGE, ErrorCode
from app.core.password_reset import (
    PURPOSE_EMAIL_BIND,
    PURPOSE_PASSWORD_RESET,
    hash_verification_code,
    verify_verification_code,
)
from app.services import mail_service
from app.services.email_bind_service import (
    CONFIRM_OK_MESSAGE,
    INVALID_CODE_MESSAGE,
    REQUEST_MESSAGE,
    _code_subject,
)

from tests.b3.conftest import (
    API,
    DEFAULT_PASSWORD,
    TEST_PEPPER,
    bind_email_via_api,
    exec_sql,
    latest_bind_code_for,
    latest_reset_code_for,
    one,
    register_token,
    req_bind,
    req_confirm_bind,
    req_reset,
    req_verify,
    rows,
    unique_email,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ══════════════════════════════════════════════════════════════════
# 1-2. 错误码契约（add-only）
# ══════════════════════════════════════════════════════════════════
def test_email_taken_error_code_contract():
    assert ErrorCode.EMAIL_TAKEN == "EMAIL_TAKEN"
    assert ERROR_HTTP_STATUS[ErrorCode.EMAIL_TAKEN] == 409
    assert ERROR_MESSAGE[ErrorCode.EMAIL_TAKEN] == "该邮箱已被其他账号使用，请更换"
    # 与 USERNAME_TAKEN 语义不同，**不得**复用
    assert ErrorCode.EMAIL_TAKEN != ErrorCode.USERNAME_TAKEN
    assert ERROR_HTTP_STATUS[ErrorCode.EMAIL_TAKEN] == ERROR_HTTP_STATUS[ErrorCode.USERNAME_TAKEN]


def test_global_error_code_count_is_nineteen():
    frozen = set(ERROR_HTTP_STATUS.keys())
    assert len(frozen) == 19, f"应为 18 冻结 ＋ 1（B3 EMAIL_TAKEN）= 19，实测 {len(frozen)}"
    assert set(ERROR_MESSAGE.keys()) == frozen
    # 18 个既有码**一个不少**（add-only 的反向证明）
    must_keep = {
        "INVALID_PARAM",
        "UNAUTHENTICATED",
        "CREDENTIALS_INVALID",
        "TOKEN_REUSED",
        "RESOURCE_NOT_FOUND",
        "USERNAME_TAKEN",
        "GOAL_TYPE_EXISTS",
        "EXPORT_IN_PROGRESS",
        "IDEMPOTENCY_CONFLICT",
        "COUNT_MISMATCH",
        "EXPORT_EXPIRED",
        "VALIDATION_FAILED",
        "PASSWORD_INVALID",
        "ACCOUNT_LOCKED",
        "SESSION_VERIFY_ABORTED",
        "SOFT_WARNING",
        "INTERNAL_ERROR",
        "SERVICE_UNAVAILABLE",
    }
    assert must_keep <= frozen
    assert frozen - must_keep == {"EMAIL_TAKEN"}


# ══════════════════════════════════════════════════════════════════
# 3-4. 蓝图 / 路由注册与鉴权
# ══════════════════════════════════════════════════════════════════
def test_blueprint_and_routes_registered(app):
    assert "email_bind" in app.blueprints
    assert len(app.blueprints) == 13, sorted(app.blueprints)

    rules = {r.rule: r for r in app.url_map.iter_rules()}
    req_rule = rules["/api/v1/auth/email/bind-request"]
    cnf_rule = rules["/api/v1/auth/email/bind-confirm"]
    assert "POST" in req_rule.methods
    assert "POST" in cnf_rule.methods
    assert req_rule.endpoint == "email_bind.request_email_bind"
    assert cnf_rule.endpoint == "email_bind.confirm_email_bind"


def test_both_endpoints_require_auth(client):
    for path, payload in (
        ("/auth/email/bind-request", {"email": "a@b.com", "current_password": DEFAULT_PASSWORD}),
        (
            "/auth/email/bind-confirm",
            {"email": "a@b.com", "code": "123456", "current_password": DEFAULT_PASSWORD},
        ),
    ):
        resp = client.post(f"{API}{path}", json=payload)
        assert resp.status_code == 401, (path, resp.get_data(as_text=True))
        assert resp.get_json()["code"] == "UNAUTHENTICATED"


# ══════════════════════════════════════════════════════════════════
# 5. 全链路日志脱敏（原始 LogRecord 判据）
# ══════════════════════════════════════════════════════════════════
def test_full_flow_logging_has_no_email_or_code(client, caplog):
    """以 pytest 捕获的**原始 ``LogRecord``** 为主判据。

    主判据不经 handler 的 ``SensitiveDataFilter`` ⇒ 证明的是「**根本没有把真值
    拼进日志消息**」，强于「过滤后没落盘」；且不依赖文件 handler 是否健康。
    """
    with caplog.at_level(logging.INFO):
        username, uid, token = register_token(client)
        email = unique_email("logcheck")
        bind_email_via_api(client, token, email)
        # 再跑一次 PR-04（触发另一条日志路径）
        exec_sql(
            "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
            "WHERE user_id=:u",
            u=uid,
        )
        req_bind(client, token, unique_email("logcheck2"))
        code_hint = latest_bind_code_for(unique_email("nope"))  # 触发一次空查（不影响日志）

    raw = caplog.text
    assert raw.strip() != "", "未捕获到任何日志记录 ⇒ 判据会空转通过"
    assert email not in raw, "日志记录出现邮箱明文"
    assert f"username={username}" not in raw, "日志记录出现用户名字段明文"
    # 6 位码可能与耗时 / request_id 偶然重合 ⇒ 用**键值形态**判据
    for code in filter(None, [latest_bind_code_for(email), code_hint]):
        for pattern in (
            f"code={code}",
            f"'code': '{code}'",
            f'"code": "{code}"',
            f"code='{code}'",
            f'code="{code}"',
        ):
            assert pattern not in raw, f"日志以字段形态出现验证码明文：{pattern}"
    # 文案本身也不得出现在日志里（防止「把 message 打出来」间接泄露语义）
    assert email not in raw


# ══════════════════════════════════════════════════════════════════
# 6. code=OK 等正常字段不得被误脱敏
# ══════════════════════════════════════════════════════════════════
def _apply_filter(msg: str) -> str:
    from app.core.logging import SensitiveDataFilter

    record = logging.LogRecord(
        name="b3.redaction",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    assert SensitiveDataFilter().filter(record) is True
    return record.getMessage()


def test_logging_does_not_over_redact_benign_code_field():
    """正常业务字段 ``code=OK`` **不得**被误脱敏（禁止裸 ``code`` 进敏感键）。"""
    msg = "email_bind_request 结果=OK code=OK username=tstb3deadbeef"
    assert _apply_filter(msg) == msg, "正常业务字段被误脱敏（脱敏必须精确到键名）"


def test_logging_redacts_email_and_verification_code_keys():
    """敏感键 ``email`` / ``verification_code`` 的值必须被 ``***`` 遮蔽。"""
    for key, value in (
        ("email", "sentinel-b3@example.invalid"),
        ("verification_code", "313373"),
    ):
        for shape in ("%s=%s", "%s: %s", "%s='%s'", '{"%s": "%s"}'):
            rendered = _apply_filter(shape % (key, value))
            assert value not in rendered, f"{key} 的值未脱敏：{rendered!r}"
            assert "***" in rendered


# ══════════════════════════════════════════════════════════════════
# 7. 邮箱绑定邮件：纯文本模板 ＋ 占位符替换
# ══════════════════════════════════════════════════════════════════
def test_email_bind_template_is_plain_text_and_renders():
    subject, body = mail_service.build_email_bind_message(code="135790", ttl_minutes=15)
    assert subject == mail_service.SUBJECT_EMAIL_BIND == "邮箱绑定验证码"
    assert subject != mail_service.SUBJECT_PASSWORD_RESET
    assert "135790" in body
    assert "15" in body
    assert "{{" not in body and "}}" not in body
    assert "<" not in body and ">" not in body, "模板应为纯文本，不得含 HTML 标签"


# ══════════════════════════════════════════════════════════════════
# 8. 内存投递箱按 purpose 分类
# ══════════════════════════════════════════════════════════════════
def test_memory_outbox_tags_purpose_for_both_flows(client):
    username, uid, token = register_token(client)
    bound = unique_email("purp")
    bind_email_via_api(client, token, bound)  # 落地已验证邮箱

    # 再发一封 email_bind 邮件（解除冷却后）
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u AND purpose='email_bind'",
        u=uid,
    )
    assert req_bind(client, token, unique_email("purp2")).status_code == 200
    # 再发一封 password_reset 邮件
    assert req_reset(client, username).status_code == 200

    purposes = [i.get("purpose") for i in mail_service.memory_outbox()]
    assert purposes.count("email_bind") == 2, purposes
    assert purposes.count("password_reset") == 1, purposes


# ══════════════════════════════════════════════════════════════════
# 9. HMAC 结构上绑定 purpose 与邮箱（单元级）
# ══════════════════════════════════════════════════════════════════
def test_hmac_binds_purpose_and_email_structurally():
    uid = 424242
    pepper = TEST_PEPPER

    # ① purpose 进 HMAC 消息体 ⇒ 同一码在不同用途下摘要不同
    h_bind = hash_verification_code(pepper, uid, PURPOSE_EMAIL_BIND, "123456")
    h_reset = hash_verification_code(pepper, uid, PURPOSE_PASSWORD_RESET, "123456")
    assert HEX64.match(h_bind) and HEX64.match(h_reset)
    assert h_bind != h_reset
    assert verify_verification_code(pepper, uid, PURPOSE_PASSWORD_RESET, "123456", h_bind) is False
    assert verify_verification_code(pepper, uid, PURPOSE_EMAIL_BIND, "123456", h_bind) is True

    # ② 邮箱进 HMAC 主体（``_code_subject``）⇒ 同一码对不同邮箱摘要不同
    h_a = hash_verification_code(pepper, uid, PURPOSE_EMAIL_BIND, _code_subject("a@x.com", "123456"))
    h_b = hash_verification_code(pepper, uid, PURPOSE_EMAIL_BIND, _code_subject("b@x.com", "123456"))
    assert h_a != h_b
    # ③ 大小写 / 空白经规范化后**等价**（canonical storage）
    h_norm = hash_verification_code(
        pepper, uid, PURPOSE_EMAIL_BIND, _code_subject("  A@X.com ", "123456")
    )
    assert h_norm == h_a


# ══════════════════════════════════════════════════════════════════
# 10. 端到端 purpose 隔离：两种码互不通用
# ══════════════════════════════════════════════════════════════════
def test_purpose_isolation_between_email_bind_and_password_reset(client):
    username, uid, token = register_token(client)
    bound = unique_email("iso")
    bind_email_via_api(client, token, bound)  # 账号 → 已验证邮箱

    # 造一个 email_bind 挑战（改绑目标）
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL 120 SECOND) "
        "WHERE user_id=:u AND purpose='email_bind'",
        u=uid,
    )
    target = unique_email("isonew")
    assert req_bind(client, token, target).status_code == 200
    code_e = latest_bind_code_for(target)
    assert code_e is not None

    # 造一个 password_reset 挑战
    assert req_reset(client, username).status_code == 200
    code_p = latest_reset_code_for(bound)
    assert code_p is not None
    assert code_e != code_p

    # ① email_bind 的码**不能**通过 PR-02（purpose 不同）
    assert req_verify(client, username, code_e).status_code == 422
    # ② password_reset 的码**不能**通过 PR-05（purpose 不同）
    wrong = req_confirm_bind(client, token, target, code_p)
    assert wrong.status_code == 422
    assert wrong.get_json()["errors"][0]["message"] == INVALID_CODE_MESSAGE
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == bound  # 未被改写

    # ③ 正确的 email_bind 码仍可完成改绑（证明上面失败确因 purpose / 邮箱不符）
    assert req_confirm_bind(client, token, target, code_e).status_code == 200
    assert one("SELECT email FROM user_account WHERE id=:u", u=uid) == target


# ══════════════════════════════════════════════════════════════════
# 11. email 配对 CHECK 约束（「已填未验证」结构上不可能）
# ══════════════════════════════════════════════════════════════════
def test_email_pair_check_constraint_exists(client):
    # ⚠️ 判据自纠（铁律②）：MySQL 8.0 的 ``information_schema.CHECK_CONSTRAINTS``
    #    **没有** ``TABLE_NAME`` 列（它是 (CONSTRAINT_SCHEMA, CONSTRAINT_NAME) 级），
    #    原判据按 ``TABLE_NAME`` 过滤会报 1054 Unknown column ⇒ 假 FAIL。
    #    正解：与 ``TABLE_CONSTRAINTS`` 按 (schema, name) 关联后按表过滤。
    cons = rows(
        "SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
        "FROM information_schema.CHECK_CONSTRAINTS cc "
        "JOIN information_schema.TABLE_CONSTRAINTS tc "
        "  ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA "
        " AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME "
        "WHERE cc.CONSTRAINT_SCHEMA = DATABASE() AND tc.TABLE_NAME = 'user_account'"
    )
    names = {str(r[0]).lower() for r in cons}
    joined = " ".join(f"{r[0]} {r[1]}" for r in cons).lower()
    assert "ck_user_account_email_pair" in names, f"未找到 email 配对 CHECK 约束，实测：{cons}"
    assert "email" in joined and "email_verified_at" in joined, (
        f"CHECK 子句未覆盖 email / email_verified_at，实测：{cons}"
    )

    # 行为证明：只写 email（不带 email_verified_at）必须被 DB 拒绝
    _, uid, _ = register_token(client)
    with pytest.raises((IntegrityError, OperationalError)):
        with session_scope() as db:
            db.execute(
                text("UPDATE user_account SET email = :e WHERE id = :u"),
                {"e": unique_email("pair"), "u": uid},
            )


# ══════════════════════════════════════════════════════════════════
# 12. 实测错误码 ⊆ 冻结集合
# ══════════════════════════════════════════════════════════════════
def test_observed_error_codes_are_all_registered(client):
    frozen = set(ERROR_HTTP_STATUS.keys())
    _, _, token = register_token(client)
    email, code = unique_email(), "000000"
    assert req_bind(client, token, email).status_code == 200

    observed = set()
    observed.add(req_bind(client, token, "bad-email").get_json()["code"])
    observed.add(req_bind(client, token, email, password="wrongpass1").get_json()["code"])
    observed.add(req_confirm_bind(client, token, email, "999999").get_json()["code"])
    observed.add(
        client.post(
            f"{API}/auth/email/bind-request", json={"email": email, "current_password": "x"}
        ).get_json()["code"]
    )
    assert observed <= frozen, f"出现未登记错误码：{observed - frozen}"
    # 中性失败文案恒定
    assert INVALID_CODE_MESSAGE in str(req_confirm_bind(client, token, email, "999999").get_json())
    assert CONFIRM_OK_MESSAGE == "邮箱绑定成功"
    assert REQUEST_MESSAGE == "如果该邮箱可绑定，我们已发送验证码"
