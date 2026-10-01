# -*- coding: utf-8 -*-
"""B1-A：日志脱敏（**实施前安全前置**）—— 正向覆盖 ＋ 反向「不误伤」双测。

对应 ``CR-F006-001`` 的 ``SR-1``~``SR-4`` / ``SR-13``，以及需求方 B1 §二 的 7 条要求：
① 精确扩展敏感键；② 不误伤普通 ``code``；③ 大小写场景；④ ``key=value`` 与 JSON 两种形态；
⑤ 不改变正常日志语义；⑥ 不记录验证码 / hash / reset token 的原始输入；⑦ 新增自动化测试。
"""
from __future__ import annotations

import logging

import pytest
from flask import Flask

from app.core.logging import (
    SensitiveDataFilter,
    _SENSITIVE_KEYS,
    configure_logging,
)

#: 需求方 B1 §二 点名必须覆盖的 9 个键（**期望值硬编码**，不取自被测对象）
REQUIRED_KEYS = (
    "email",
    "verification_code",
    "reset_token",
    "password_reset_token",
    "access_token",
    "refresh_token",
    "password",
    "password_hash",
    "smtp_password",
)

#: 占位敏感值（**全部为伪造值**，仅用于断言脱敏行为）
FAKE = {
    "email": "someone@example.com",
    "verification_code": "123456",
    "reset_token": "AAAbbbCCCdddEEEfffGGG",
    "password_reset_token": "AAAbbbCCCdddEEEfffGGG",
    "access_token": "eyJhbGciOiJIUzI1NiJ9.FAKE.FAKE",
    "refresh_token": "FAKE-refresh-token-value",
    "password": "Str0ngPassw0rd",
    "password_hash": "$2b$12$FAKEHASHFAKEHASHFAKEHA",
    "smtp_password": "FAKE-smtp-password",
}


def mask(message: str) -> str:
    """经 :class:`SensitiveDataFilter` 后的最终消息（与 ``record.getMessage()`` 同路径）。"""
    record = logging.LogRecord("t", logging.INFO, "", 0, message, (), None)
    SensitiveDataFilter().filter(record)
    return record.getMessage()


# ══════════════════════════════════════════════════════════════════
# 1. 正向：9 个必须覆盖的键，值一律不得残留
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_required_key_is_redacted(key: str) -> None:
    value = FAKE[key]
    out = mask(f"{key}={value}")
    assert value not in out, f"{key} 的值未脱敏：{out}"
    assert "***" in out


@pytest.mark.parametrize(
    "key",
    ("verification_code", "code_hash", "reset_token", "reset_token_hash",
     "password_reset_token", "password_reset_token_hash", "token_hash",
     "access_token_hash", "refresh_token_hash", "password_reset_pepper"),
)
def test_credential_equivalent_keys_are_redacted(key: str) -> None:
    """**凭证等价物**（hash / pepper）同样必须脱敏（``SR-2`` / ``SR-4``）。"""
    out = mask(f"{key}=DEADBEEF0123456789")
    assert "DEADBEEF0123456789" not in out
    assert f"{key}=***" == out


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_case_insensitive_keys(key: str) -> None:
    """③ 大小写场景：``EMAIL=`` / ``Reset_Token=`` / ``SMTP_PASSWORD=`` 等一律覆盖。"""
    value = FAKE[key]
    for variant in (key.upper(), key.title(), "".join(
            c.upper() if i % 2 else c for i, c in enumerate(key))):
        out = mask(f"{variant}={value}")
        assert value not in out, f"{variant} 未脱敏：{out}"


def test_json_form_is_redacted_and_still_parsable() -> None:
    """④ JSON 形态：键在引号内的形式也必须覆盖，且输出仍是**合法 JSON**。"""
    import json

    line = '{"email": "someone@example.com", "code": "OK", "user_id": 42}'
    out = mask(line)
    assert "someone@example.com" not in out
    parsed = json.loads(out)  # 必须仍是合法 JSON（引号形态被保留）
    assert parsed["email"] == "***"
    assert parsed["code"] == "OK"


def test_quoted_and_colon_separated_forms() -> None:
    assert "Str0ngPassw0rd" not in mask("password: Str0ngPassw0rd")
    assert "Str0ngPassw0rd" not in mask("password: 'Str0ngPassw0rd'")
    assert "Str0ngPassw0rd" not in mask('password="Str0ngPassw0rd"')
    assert "Str0ngPassw0rd" not in mask("password = Str0ngPassw0rd")


# ══════════════════════════════════════════════════════════════════
# 2. 反向：**不得误伤**普通业务字段（② 的核心判据）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "line",
    (
        "code=OK",
        "code=NOT_FOUND",
        "code=INVALID_PARAM",
        "resp code=200",
        '{"code": "OK", "message": "done"}',
        "biz code: OK",
    ),
)
def test_plain_code_is_not_redacted(line: str) -> None:
    assert mask(line) == line, f"普通业务 code 被误脱敏：{mask(line)}"


def test_no_bare_code_key_in_allowlist() -> None:
    """**结构判据**：白名单里绝不允许出现裸 ``code``（防日后回退）。"""
    assert "code" not in _SENSITIVE_KEYS
    assert not any(k.strip().lower() == "code" for k in _SENSITIVE_KEYS)


@pytest.mark.parametrize(
    "line",
    (
        "email_verified_at=2026-01-01 00:00:00",
        "access_token_id=deadbeefdeadbeefdeadbeefdeadbeef",
        "expires_at=2026-01-01 00:00:00",
        "attempt_count=3",
        "purpose=password_reset",
        "request_id=abcdef",
        "status=active revoked_at=NULL",
        "goal_type=weight metric_type=weight",
    ),
)
def test_non_sensitive_fields_are_untouched(line: str) -> None:
    """⑤ 不改变正常日志语义：非敏感字段逐字符原样保留。"""
    assert mask(line) == line, f"非敏感字段被改动：{mask(line)}"


def test_ordinary_log_line_is_byte_identical() -> None:
    """正常业务日志逐字节不变（无任何敏感键 ⇒ 过滤器是 no-op）。"""
    line = "GET /api/v1/records -> 200 (12.3ms)"
    assert mask(line) == line


@pytest.mark.parametrize("line", ("sub_token=abc", "my_password_x=abc", "x_secret_y=abc"))
def test_prefix_key_does_not_cover_underscore_compounds(line: str) -> None:
    """⚠️ **机制证据**：``_`` 属词字符 ⇒ ``\\b`` 不成立 ⇒ 前缀键（``token`` / ``password`` /
    ``secret``）**覆盖不到**含下划线的复合键名。

    这正是「必须逐条枚举复合键名」的原因；若把该测试当作「漏脱敏」来修，
    就该往 :data:`_SENSITIVE_KEYS` 里补**精确键名**，而不是改成正则模糊匹配
    （模糊匹配会引入 ``code`` 误伤面）。
    """
    assert mask(line) == line


def test_underscore_compounds_are_covered_once_enumerated() -> None:
    """本批已枚举的复合键名逐一被覆盖（与上一条互为对照）。"""
    for line in (
        "reset_token=abc",
        "password_reset_token=abc",
        "refresh_token_hash=abc",
        "access_token_hash=abc",
        "verification_code=abc",
        "code_hash=abc",
    ):
        assert "abc" not in mask(line), f"{line} 仍未覆盖"


# ══════════════════════════════════════════════════════════════════
# 3. 端到端：真实落到日志文件的内容必须已脱敏（写入临时目录，不污染 app.log）
# ══════════════════════════════════════════════════════════════════
def test_end_to_end_file_output_is_redacted(tmp_path, app) -> None:  # noqa: ANN001
    """把日志真正写进文件后逐字检查 —— 证明过滤器挂在**实际 handler** 上。

    ⚠️ **装置陷阱（B1 实测）——「全量运行才 FAIL、单独跑就过」的真因**
    （铁律③：修 harness，**不得回流为产品已修复**）：

    收尾**不能**写成 ``configure_logging(app)``。该函数除了换 handler，还会注册
    ``@app.before_request`` / ``@app.after_request``；而会话级 ``app`` 在本用例之前
    早已处理过请求（``_got_first_request=True``）⇒ Flask 直接抛
    ``AssertionError: The setup method 'before_request' can no longer be called``。
    由于它发生在 ``finally`` 里，**脱敏断言其实全部通过**，测试仍然 FAIL；
    又因为单独运行本文件时 app 尚未处理过任何请求 ⇒ 该路径不触发 ⇒ 看起来「隔离过、全量挂」。
    正解 = **原样还原 root 的 handler 集合**，不再调用 ``configure_logging``。
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    probe = Flask("b1_logging_probe")
    probe.config.update(
        LOG_LEVEL="INFO",
        LOG_DIR=str(tmp_path),
        LOG_RETENTION_DAYS=1,
    )
    configure_logging(probe)
    try:
        with probe.app_context():
            probe.logger.info(
                "reset requested email=%s verification_code=%s",
                "someone@example.com",
                "123456",
            )
            probe.logger.info("biz code=OK done")
        raw = (tmp_path / "app.log").read_text(encoding="utf-8")
    finally:
        # 只关掉本探针新装的 handler，再逐字还原会话级 app 原有的 handler 集合
        # ⇒ 后续用例的日志仍落回 logs/app.log，且不触碰任何 Flask 装置 API。
        for h in list(root.handlers):
            root.removeHandler(h)
            if h not in saved_handlers:
                try:
                    h.close()
                except Exception:  # noqa: BLE001
                    pass
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)

    assert "someone@example.com" not in raw, "邮箱明文落盘"
    assert "123456" not in raw, "验证码明文落盘"
    assert "email=***" in raw and "verification_code=***" in raw
    assert "code=OK done" in raw, "普通 code=OK 被误伤"


def test_filter_attached_to_all_handlers(app) -> None:  # noqa: ANN001
    """既有架构下（console + 按天轮转文件）**两个业务 handler** 都必须带脱敏过滤器。

    ⚠️ 测试装置注意：pytest 的 logging 插件会往根 logger 注入 ``LogCaptureHandler``，
    它**不受本模块控制**、也不参与落盘 ⇒ 判据只针对 ``configure_logging``
    注册的那两个 handler（这类「装置自身引入的 handler」不得反向要求产品去修，
    铁律③：修 harness 不得回流为产品已修复）。
    """
    root = logging.getLogger()
    scrubbed = [
        h for h in root.handlers
        if any(isinstance(f, SensitiveDataFilter) for f in h.filters)
    ]
    assert len(scrubbed) == 2, f"带脱敏过滤器的 handler 数={len(scrubbed)}（期望 2）"
    kinds = {type(h).__name__ for h in scrubbed}
    assert "TimedRotatingFileHandler" in kinds, f"缺少按天轮转文件 handler：{kinds}"
    file_handlers = [h for h in scrubbed if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    assert str(file_handlers[0].baseFilename).replace("\\", "/").endswith("logs/app.log")
