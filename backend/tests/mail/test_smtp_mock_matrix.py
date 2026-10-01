# -*- coding: utf-8 -*-
"""MAIL-DELIVERY-1 · Mock SMTP 测试矩阵（授权 §十三 A~AR）。

**零真实网络**：全部 smtp 用例以 ``FakeSMTP`` 替换 ``smtplib.SMTP``。
**零 secret**：所有口令均为 ``dummy-app-password`` 等明显虚构值。

用例编号与授权 §十三 一一对应（名称前缀 ``test_a_`` ~ ``test_ar_``）。
"""
from __future__ import annotations

import ast
import inspect
import logging
import smtplib
from pathlib import Path

import pytest

from app.services import mail_service

from .conftest import (
    FAKE_SMTP_PASSWORD,
    FakeSMTP,
    req_bind,
    req_reset,
    smtp_cfg,
)

MAIL_SERVICE_PATH = Path(mail_service.__file__)


# ══════════════════════════════════════════════════════════════════
# A. memory 原行为不变（缺省后端仍 memory，投递进进程内箱）
# ══════════════════════════════════════════════════════════════════
def test_a_memory_backend_original_behavior_unchanged():
    result = mail_service.send_password_reset_code(
        {"MAIL_BACKEND": "memory"}, to_email="someone@example.com", code="654321", ttl_minutes=15
    )
    assert result.delivered is True
    assert result.backend == "memory"
    box = mail_service.memory_outbox()
    assert len(box) == 1
    assert box[0]["code"] == "654321"
    assert box[0]["purpose"] == "password_reset"


def test_a_default_backend_is_still_memory():
    assert mail_service.resolve_backend({}) == "memory"
    assert mail_service.resolve_backend(None) == "memory"
    assert mail_service.resolve_backend({"MAIL_BACKEND": "bogus"}) == "memory"


# ══════════════════════════════════════════════════════════════════
# B. memory 后端**不读** SMTP_PASSWORD（AST 静态 ＋ 运行期双证）
# ══════════════════════════════════════════════════════════════════
def test_b_memory_backend_never_reads_smtp_password_statically():
    """AST：模块内**不得**出现「像真凭据」的硬编码字面量。

    新契约（授权 §十）：允许 smtp 分支读取 ``SMTP_*``；但必须**只从 cfg 读**，
    且**不得**出现硬编码口令字面量。
    """
    tree = ast.parse(MAIL_SERVICE_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            # ── 判据收窄（本批自纠）：只考察**ASCII** 串 ──
            # 中文 docstring 往往「长、无空格、含字母数字」⇒ 原启发式会误伤
            # 纯说明文字。凭据形态必然是 ASCII（口令 / 应用专用密码）。
            if not v.isascii():
                continue
            if len(v) >= 16 and (" " not in v) and any(c.isdigit() for c in v) and any(
                c.isalpha() for c in v
            ):
                if not any(tok in v for tok in ("/", "\\", ".py", ".txt", "%s", "{{", "https")):
                    offenders.append(v)
    assert offenders == [], f"mail_service 出现疑似硬编码凭据：{offenders}"
    # ② SMTP_PASSWORD 只能来自 cfg（不允许直接读取 os.environ）
    src = MAIL_SERVICE_PATH.read_text(encoding="utf-8")
    assert "os.environ" not in src, "mail_service 不得直接读取 os.environ（密钥须经 config）"


def test_b_memory_backend_run_does_not_require_smtp_config():
    """memory 后端在**完全没有任何 SMTP_* 配置**时照常投递。"""
    cfg = {"MAIL_BACKEND": "memory"}  # 无任何 SMTP_*
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="111222", ttl_minutes=15
    )
    assert result.delivered is True
    assert result.backend == "memory"


# ══════════════════════════════════════════════════════════════════
# C. smtp 配置读取正确
# ══════════════════════════════════════════════════════════════════
def test_c_smtp_config_is_read_correctly(fake_smtp):
    cfg = smtp_cfg()
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="333444", ttl_minutes=15
    )
    assert result.delivered is True
    assert result.backend == "smtp"
    assert len(fake_smtp.instances) == 1
    inst = fake_smtp.instances[0]
    assert inst.host == "smtp.example.invalid"
    assert int(inst.port) == 587
    assert int(inst.timeout) == 10
    assert inst.logged_in == ("healthtrack@example.invalid", FAKE_SMTP_PASSWORD)
    assert inst.tls_started is True


# ══════════════════════════════════════════════════════════════════
# D. SMTP_HOST 缺失 / 非法 ⇒ fail-closed（delivered=False，不连网）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("host", [None, "", "   ", "CHANGE_ME", "change_me_host"])
def test_d_smtp_host_missing_or_invalid_fails_closed(fake_smtp, host):
    cfg = smtp_cfg(SMTP_HOST=host)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="555666", ttl_minutes=15
    )
    assert result.delivered is False
    assert result.backend == "smtp"
    assert fake_smtp.instances == [], "配置非法时**不得**建立连接"


# ══════════════════════════════════════════════════════════════════
# E. SMTP_PORT 非法 ⇒ fail-closed
#    ⚠️ 判据口径：`""` / 未设置 = **未配置** ⇒ 落默认 587（不属「非法」）；
#       非空但不可解析 / 越界 ⇒ fail-closed。
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("port", ["0", "-1", "abc", "70000"])
def test_e_smtp_port_invalid_fails_closed(fake_smtp, port):
    cfg = smtp_cfg(SMTP_PORT=port)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="777888", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances == []


def test_e_smtp_port_blank_means_unset_and_falls_back_to_default(fake_smtp):
    """空串 = **未配置** ⇒ 落默认 587（与 ``config._get_int`` 同口径）。"""
    cfg = smtp_cfg(SMTP_PORT="")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="777888", ttl_minutes=15
    )
    assert result.delivered is True
    assert int(fake_smtp.instances[0].port) == 587


def test_e_smtp_port_valid_uses_supplied_value(fake_smtp):
    cfg = smtp_cfg(SMTP_PORT="2525")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="777888", ttl_minutes=15
    )
    assert result.delivered is True
    assert int(fake_smtp.instances[0].port) == 2525


# ══════════════════════════════════════════════════════════════════
# F. SMTP_USERNAME 缺失 ⇒ fail-closed
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("user", [None, "", "  ", "CHANGE_ME"])
def test_f_smtp_username_missing_fails_closed(fake_smtp, user):
    cfg = smtp_cfg(SMTP_USERNAME=user)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="999000", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances == []


# ══════════════════════════════════════════════════════════════════
# G. SMTP_PASSWORD 缺失 ⇒ fail-closed
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("pwd", [None, "", "   ", "CHANGE_ME"])
def test_g_smtp_password_missing_fails_closed(fake_smtp, pwd):
    cfg = smtp_cfg(SMTP_PASSWORD=pwd)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="121314", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances == []


# ══════════════════════════════════════════════════════════════════
# H. SMTP_FROM 行为（配置 / 缺失 fallback / 两者皆缺 ⇒ fail-closed）
# ══════════════════════════════════════════════════════════════════
def test_h_smtp_from_explicit_is_used(fake_smtp):
    cfg = smtp_cfg(SMTP_FROM="custom-sender@example.invalid")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="151617", ttl_minutes=15
    )
    assert result.delivered is True
    msg = fake_smtp.instances[0].sent[0]
    assert "custom-sender@example.invalid" in str(msg["From"])


def test_h_smtp_from_missing_falls_back_to_username(fake_smtp):
    """未配置 ``SMTP_FROM`` 时 fallback 到 ``SMTP_USERNAME``（详见报告 §H）。"""
    cfg = smtp_cfg(SMTP_FROM=None)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="151617", ttl_minutes=15
    )
    assert result.delivered is True
    msg = fake_smtp.instances[0].sent[0]
    assert "healthtrack@example.invalid" in str(msg["From"])


def test_h_smtp_from_and_username_both_missing_fails_closed(fake_smtp):
    cfg = smtp_cfg(SMTP_FROM=None, SMTP_USERNAME=None)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="151617", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances == []


def test_h_message_headers_and_body_are_correct(fake_smtp):
    cfg = smtp_cfg()
    result = mail_service.send_password_reset_code(
        cfg, to_email="recipient@example.invalid", code="246802", ttl_minutes=15
    )
    assert result.delivered is True
    msg = fake_smtp.instances[0].sent[0]
    assert msg["To"] == "recipient@example.invalid"
    assert msg["Subject"] == mail_service.SUBJECT_PASSWORD_RESET
    body = msg.get_content()
    assert "246802" in body
    assert "15" in body


# ══════════════════════════════════════════════════════════════════
# I. SMTP_TIMEOUT 行为
# ══════════════════════════════════════════════════════════════════
def test_i_smtp_timeout_is_applied(fake_smtp):
    cfg = smtp_cfg(SMTP_TIMEOUT="25")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="181920", ttl_minutes=15
    )
    assert result.delivered is True
    assert int(fake_smtp.instances[0].timeout) == 25


@pytest.mark.parametrize("tmo", ["0", "-5", "abc"])
def test_i_smtp_timeout_invalid_falls_back_to_default(fake_smtp, tmo):
    """非法 timeout ⇒ 回落默认值 10（不得因配置瑕疵而中断投递）。"""
    cfg = smtp_cfg(SMTP_TIMEOUT=tmo)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="181920", ttl_minutes=15
    )
    assert result.delivered is True
    assert int(fake_smtp.instances[0].timeout) == 10


# ══════════════════════════════════════════════════════════════════
# J / K. SMTP_USE_TLS 显式布尔解析（**禁止 bool("false") 陷阱**）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("flag", ["true", "TRUE", "True", "1", "yes", "on"])
def test_j_smtp_use_tls_truthy_starts_tls(fake_smtp, flag):
    cfg = smtp_cfg(SMTP_USE_TLS=flag)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="212223", ttl_minutes=15
    )
    assert result.delivered is True
    inst = fake_smtp.instances[0]
    assert inst.tls_started is True
    assert inst.calls.index("starttls") < inst.calls.index("login")


@pytest.mark.parametrize("flag", ["false", "FALSE", "False", "0", "no", "off"])
def test_k_smtp_use_tls_falsy_skips_tls(fake_smtp, flag):
    """⚠️ 关键判据：``"false"`` **不得**被 ``bool()`` 误判为 True。"""
    cfg = smtp_cfg(SMTP_USE_TLS=flag)
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="242526", ttl_minutes=15
    )
    assert result.delivered is True
    inst = fake_smtp.instances[0]
    assert inst.tls_started is False, f"SMTP_USE_TLS={flag!r} 被误判为 True"
    assert "starttls" not in inst.calls


def test_k_smtp_use_tls_blank_means_unset_defaults_to_true(fake_smtp):
    """空串 = **未配置** ⇒ 落默认 ``True``（与「显式 false」严格区分）。"""
    cfg = smtp_cfg(SMTP_USE_TLS="")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="242526", ttl_minutes=15
    )
    assert result.delivered is True
    assert fake_smtp.instances[0].tls_started is True


def test_k_smtp_use_tls_invalid_value_fails_closed(fake_smtp):
    """无法明确解析为布尔的取值 ⇒ fail-closed（不猜、不默认开）。"""
    cfg = smtp_cfg(SMTP_USE_TLS="maybe")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="242526", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances == []


def test_k_smtp_use_tls_unset_defaults_to_true(fake_smtp):
    cfg = smtp_cfg()
    cfg.pop("SMTP_USE_TLS")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="242526", ttl_minutes=15
    )
    assert result.delivered is True
    assert fake_smtp.instances[0].tls_started is True


# ══════════════════════════════════════════════════════════════════
# L. connect 成功 ⇒ 走 _send_smtp，建立连接（无持久副作用）
# ══════════════════════════════════════════════════════════════════
def test_l_connect_success_creates_connection(fake_smtp):
    cfg = smtp_cfg()
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="272829", ttl_minutes=15
    )
    assert result.delivered is True
    assert len(fake_smtp.instances) == 1


# ══════════════════════════════════════════════════════════════════
# M. starttls 成功（协议链顺序）
# ══════════════════════════════════════════════════════════════════
def test_m_starttls_success_protocol_order(fake_smtp):
    cfg = smtp_cfg(SMTP_USE_TLS="true")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="303132", ttl_minutes=15
    )
    assert result.delivered is True
    calls = fake_smtp.instances[0].calls
    # 允许 ehlo 出现两次（STARTTLS 前后各一次），但相对次序必须正确
    assert calls.count("starttls") == 1
    assert calls.index("starttls") < calls.index("login") < calls.index("send_message")


# ══════════════════════════════════════════════════════════════════
# N. login 成功（凭据来自 cfg，**非硬编码**）
# ══════════════════════════════════════════════════════════════════
def test_n_login_success_uses_cfg_credentials(fake_smtp):
    cfg = smtp_cfg(SMTP_USERNAME="other-user@example.invalid", SMTP_PASSWORD="another-dummy-pw")
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="333435", ttl_minutes=15
    )
    assert result.delivered is True
    assert fake_smtp.instances[0].logged_in == (
        "other-user@example.invalid",
        "another-dummy-pw",
    )


# ══════════════════════════════════════════════════════════════════
# O. send_message 成功（载荷正确）
# ══════════════════════════════════════════════════════════════════
def test_o_send_message_success_payload(fake_smtp):
    cfg = smtp_cfg()
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="363738", ttl_minutes=15
    )
    assert result.delivered is True
    sent = fake_smtp.instances[0].sent
    assert len(sent) == 1
    assert "363738" in sent[0].get_content()


# ══════════════════════════════════════════════════════════════════
# P. connection failure ⇒ delivered=False
# ══════════════════════════════════════════════════════════════════
def test_p_connection_failure(fake_smtp):
    fake_smtp.fail_on = "connect"
    fake_smtp.fail_exc = smtplib.SMTPConnectError(421, b"cannot connect")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="394041", ttl_minutes=15
    )
    assert result.delivered is False
    assert result.backend == "smtp"


# ══════════════════════════════════════════════════════════════════
# Q. TLS failure ⇒ delivered=False
# ══════════════════════════════════════════════════════════════════
def test_q_tls_failure(fake_smtp):
    fake_smtp.fail_on = "starttls"
    fake_smtp.fail_exc = smtplib.SMTPNotSupportedError("STARTTLS not supported")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="424344", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances[0].logged_in is None, "TLS 失败后**不得**继续登录"


# ══════════════════════════════════════════════════════════════════
# R. authentication failure ⇒ delivered=False
# ══════════════════════════════════════════════════════════════════
def test_r_authentication_failure(fake_smtp):
    fake_smtp.fail_on = "login"
    fake_smtp.fail_exc = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="454647", ttl_minutes=15
    )
    assert result.delivered is False
    assert fake_smtp.instances[0].sent == [], "认证失败后**不得**继续发送"


# ══════════════════════════════════════════════════════════════════
# S. send failure ⇒ delivered=False
# ══════════════════════════════════════════════════════════════════
def test_s_send_failure(fake_smtp):
    fake_smtp.fail_on = "send"
    fake_smtp.fail_exc = smtplib.SMTPDataError(554, b"message rejected")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="484950", ttl_minutes=15
    )
    assert result.delivered is False


# ══════════════════════════════════════════════════════════════════
# T. timeout ⇒ delivered=False
# ══════════════════════════════════════════════════════════════════
def test_t_timeout(fake_smtp):
    fake_smtp.fail_on = "connect"
    fake_smtp.fail_exc = TimeoutError("timed out")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="515253", ttl_minutes=15
    )
    assert result.delivered is False


def test_t_socket_timeout_on_send(fake_smtp):
    fake_smtp.fail_on = "send"
    fake_smtp.fail_exc = smtplib.SMTPServerDisconnected("connection reset")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="515253", ttl_minutes=15
    )
    assert result.delivered is False


# ══════════════════════════════════════════════════════════════════
# U. 未知 SMTP exception ⇒ delivered=False（**绝不冒泡**）
# ══════════════════════════════════════════════════════════════════
def test_u_unknown_exception_is_swallowed(fake_smtp):
    fake_smtp.fail_on = "send"
    fake_smtp.fail_exc = RuntimeError("unexpected SMTP internals")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="545556", ttl_minutes=15
    )
    assert result.delivered is False
    assert result.backend == "smtp"


# ══════════════════════════════════════════════════════════════════
# V. delivered=True 仅在**真实 mock send 成功**时出现
# ══════════════════════════════════════════════════════════════════
def test_v_delivered_true_only_after_successful_send(fake_smtp):
    cfg = smtp_cfg()
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="575859", ttl_minutes=15
    )
    assert result.delivered is True
    inst = fake_smtp.instances[0]
    assert "send_message" in inst.calls
    assert len(inst.sent) == 1
    assert inst._closed is True, "投递后连接必须被关闭"


def test_v_delivered_false_if_send_not_reached(fake_smtp):
    fake_smtp.fail_on = "login"
    fake_smtp.fail_exc = smtplib.SMTPAuthenticationError(535, b"nope")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="575859", ttl_minutes=15
    )
    assert result.delivered is False
    assert "send_message" not in fake_smtp.instances[0].calls


# ══════════════════════════════════════════════════════════════════
# W. delivered=False 覆盖全部失败分支
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "stage,exc",
    [
        ("connect", smtplib.SMTPConnectError(421, b"x")),
        ("starttls", smtplib.SMTPNotSupportedError("x")),
        ("login", smtplib.SMTPAuthenticationError(535, b"x")),
        ("send", smtplib.SMTPDataError(554, b"x")),
    ],
)
def test_w_all_failure_stages_yield_delivered_false(fake_smtp, stage, exc):
    fake_smtp.fail_on = stage
    fake_smtp.fail_exc = exc
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="606162", ttl_minutes=15
    )
    assert result.delivered is False
    assert result.backend == "smtp"
    assert result.detail, "失败时应给出**脱敏**的类别说明"


def test_w_config_failures_yield_delivered_false(fake_smtp):
    """配置类失败（缺 host / 缺口令）同样为 ``delivered=False``。"""
    for bad in (smtp_cfg(SMTP_HOST=None), smtp_cfg(SMTP_PASSWORD=None), smtp_cfg(SMTP_PORT="abc")):
        result = mail_service.send_password_reset_code(
            bad, to_email="someone@example.com", code="606162", ttl_minutes=15
        )
        assert result.delivered is False
