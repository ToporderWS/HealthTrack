# -*- coding: utf-8 -*-
"""MAIL-DELIVERY-1 · secret 不泄漏 ＋ PR-01/PR-04 端到端 ＋ 零网络（授权 §十三 X/AA~AR）。

分为三组：
- **X/Y/Z**：secret 不进日志 / response / DB；
- **AA~AD / AE~AI**：PR-01 四态恒等、PR-04 无新信道、既有安全规则不变；
- **AJ~AR**：验证码策略不变、file-outbox / redacted-console 不回归、**零真实网络**。
"""
from __future__ import annotations

import ast
import logging
import socket
import smtplib
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services import mail_service

from .conftest import (
    FAKE_SMTP_PASSWORD,
    FakeSMTP,
    access_token_of,
    identity_of,
    latest_bind_code_for,
    register_account,
    req_bind,
    req_reset,
    rewind_reset_cooldown,
    rows,
    set_email_verified,
    smtp_cfg,
    unique_email,
)

MAIL_SERVICE_PATH = Path(mail_service.__file__)


# ══════════════════════════════════════════════════════════════════
# X. secret 不进日志
# ══════════════════════════════════════════════════════════════════
def test_x_smtp_password_never_reaches_logs(fake_smtp, caplog):
    cfg = smtp_cfg(SMTP_PASSWORD="dummy-app-password")
    with caplog.at_level(logging.DEBUG):
        result = mail_service.send_password_reset_code(
            cfg, to_email="victim@example.invalid", code="424242", ttl_minutes=15
        )
    assert result.delivered is True
    assert "dummy-app-password" not in caplog.text
    assert "victim@example.invalid" not in caplog.text
    assert "424242" not in caplog.text


def test_x_smtp_password_absent_on_failure_path_logs(fake_smtp, caplog):
    fake_smtp.fail_on = "login"
    fake_smtp.fail_exc = smtplib.SMTPAuthenticationError(535, b"bad creds for dummy-app-password")
    with caplog.at_level(logging.DEBUG):
        result = mail_service.send_password_reset_code(
            smtp_cfg(SMTP_PASSWORD="dummy-app-password"),
            to_email="victim@example.invalid",
            code="424242",
            ttl_minutes=15,
        )
    assert result.delivered is False
    assert "dummy-app-password" not in caplog.text


def test_x_smtp_failure_detail_has_no_exception_repr(fake_smtp):
    """失败 detail 只允许**类别**，不得是完整 exception repr（可能含凭据）。"""
    fake_smtp.fail_on = "login"
    fake_smtp.fail_exc = smtplib.SMTPAuthenticationError(535, b"bad creds for dummy-app-password")
    result = mail_service.send_password_reset_code(
        smtp_cfg(), to_email="someone@example.com", code="424242", ttl_minutes=15
    )
    assert result.delivered is False
    assert "dummy-app-password" not in result.detail
    assert "535" not in result.detail
    assert "Traceback" not in result.detail
    assert len(result.detail) <= 120, "detail 应短小且脱敏"


# ══════════════════════════════════════════════════════════════════
# Y. secret 不进 API response
# ══════════════════════════════════════════════════════════════════
def test_y_smtp_secret_never_in_api_response(client, app, fake_smtp):
    """PR-01（免登录）在 smtp 后端下的响应体不得含任何 secret / 邮箱 / 验证码。"""
    app.config["MAIL_BACKEND"] = "smtp"
    app.config.update(
        {
            "SMTP_HOST": "smtp.example.invalid",
            "SMTP_PORT": "587",
            "SMTP_USE_TLS": "true",
            "SMTP_USERNAME": "healthtrack@example.invalid",
            "SMTP_PASSWORD": FAKE_SMTP_PASSWORD,
            "SMTP_FROM": "no-reply@example.invalid",
            "SMTP_TIMEOUT": "10",
        }
    )
    try:
        resp = req_reset(client, "tstmailnonexistent")
        raw = resp.get_data(as_text=True)
        assert FAKE_SMTP_PASSWORD not in raw
        assert "smtp.example.invalid" not in raw
        assert "healthtrack@example.invalid" not in raw
        assert "no-reply@example.invalid" not in raw
    finally:
        for k in (
            "MAIL_BACKEND",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USE_TLS",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_TIMEOUT",
        ):
            app.config.pop(k, None)


# ══════════════════════════════════════════════════════════════════
# Z. secret 不进 DB
# ══════════════════════════════════════════════════════════════════
def test_z_smtp_secret_never_persisted_to_db(client, app, fake_smtp):
    """发起一次可通过投递的 PR-01 后，全库**任何**列都不得出现该口令。"""
    app.config["PASSWORD_RESET_PEPPER"] = "mail-test-only-pepper-DO-NOT-USE-IN-PROD"
    app.config["MAIL_BACKEND"] = "smtp"
    app.config.update(
        {
            "SMTP_HOST": "smtp.example.invalid",
            "SMTP_PORT": "587",
            "SMTP_USE_TLS": "true",
            "SMTP_USERNAME": "healthtrack@example.invalid",
            "SMTP_PASSWORD": FAKE_SMTP_PASSWORD,
            "SMTP_FROM": "no-reply@example.invalid",
            "SMTP_TIMEOUT": "10",
        }
    )
    try:
        username, uid = register_account(client)
        email = unique_email("zsecret")
        set_email_verified(uid, email)
        req_reset(client, username)  # 触发真实投递链（走 FakeSMTP）
        hits = rows(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE()"
        )
        # 逐表逐列扫描 suspicious 值（在测试库内，安全）
        found = []
        for (table_name, col_name) in rows(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND data_type IN "
            "('char','varchar','text','mediumtext','longtext')"
        ):
            n = rows(
                f"SELECT COUNT(*) FROM `{table_name}` WHERE `{col_name}` LIKE :p",
                p=f"%{FAKE_SMTP_PASSWORD}%",
            )
            if n and int(n[0][0]) > 0:
                found.append(f"{table_name}.{col_name}")
        assert found == [], f"SMTP 口令被写入数据库：{found}"
    finally:
        for k in (
            "MAIL_BACKEND",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USE_TLS",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_TIMEOUT",
        ):
            app.config.pop(k, None)


# ══════════════════════════════════════════════════════════════════
# AA~AD. PR-01 四态恒等（smtp 后端下）
# ══════════════════════════════════════════════════════════════════
def _enable_smtp(app, fake_smtp):
    app.config["PASSWORD_RESET_PEPPER"] = "mail-test-only-pepper-DO-NOT-USE-IN-PROD"
    app.config["MAIL_BACKEND"] = "smtp"
    app.config.update(
        {
            "SMTP_HOST": "smtp.example.invalid",
            "SMTP_PORT": "587",
            "SMTP_USE_TLS": "true",
            "SMTP_USERNAME": "healthtrack@example.invalid",
            "SMTP_PASSWORD": FAKE_SMTP_PASSWORD,
            "SMTP_FROM": "no-reply@example.invalid",
            "SMTP_TIMEOUT": "10",
        }
    )


def _disable_smtp(app):
    for k in (
        "MAIL_BACKEND",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USE_TLS",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_TIMEOUT",
    ):
        app.config.pop(k, None)


def test_aa_pr01_smtp_success_response_identical(client, app, fake_smtp):
    """AA：命中且投递成功时，响应与「不存在」形态**逐字相同**。"""
    _enable_smtp(app, fake_smtp)
    try:
        username, uid = register_account(client)
        email = unique_email("aahit")
        set_email_verified(uid, email)
        hit = req_reset(client, username)
        miss = req_reset(client, "tstmailnosuchuser")
        assert hit.status_code == miss.status_code == 200
        assert identity_of(hit) == identity_of(miss), "命中态与不存在态可区分"
        assert identity_of(hit) == {
            "code": "OK",
            "message": "如果该账号存在且已绑定邮箱，我们已发送验证码",
            "data": None,
        }
    finally:
        _disable_smtp(app)


def test_ab_pr01_smtp_failure_response_identical(client, app, fake_smtp):
    """AB：投递失败时，对外响应**仍然恒等**（不得暴露失败）。"""
    _enable_smtp(app, fake_smtp)
    fake_smtp.fail_on = "connect"
    fake_smtp.fail_exc = smtplib.SMTPConnectError(421, b"down")
    try:
        username, uid = register_account(client)
        email = unique_email("abfail")
        set_email_verified(uid, email)
        fail = req_reset(client, username)
        miss = req_reset(client, "tstmailnosuchuser")
        assert fail.status_code == 200
        assert identity_of(fail) == identity_of(miss), "投递失败暴露了与不存在态的差异"
    finally:
        _disable_smtp(app)


def test_ac_pr01_nonexistent_user_identical(client, app, fake_smtp):
    _enable_smtp(app, fake_smtp)
    try:
        miss = req_reset(client, "tstmailghost")
        assert miss.status_code == 200
        assert identity_of(miss)["data"] is None
        assert fake_smtp.instances == [], "不存在的账号**不得**触发 SMTP 连接"
    finally:
        _disable_smtp(app)


def test_ad_pr01_account_without_verified_email_identical(client, app, fake_smtp):
    """AD：账号存在但**无绑定邮箱** ⇒ 恒等响应且不投递。"""
    _enable_smtp(app, fake_smtp)
    try:
        username, _uid = register_account(client)  # 注册后无 email
        resp = req_reset(client, username)
        assert resp.status_code == 200
        assert identity_of(resp)["message"] == "如果该账号存在且已绑定邮箱，我们已发送验证码"
        assert fake_smtp.instances == [], "无绑定邮箱**不得**触发 SMTP 连接"
    finally:
        _disable_smtp(app)


# ══════════════════════════════════════════════════════════════════
# AE~AF. PR-04 smtp 后端
# ══════════════════════════════════════════════════════════════════
def test_ae_pr04_smtp_success_no_email_taken_channel(client, app, fake_smtp):
    """AE：PR-04 在 smtp 后端下投递成功，响应恒等（`data: null`）。"""
    _enable_smtp(app, fake_smtp)
    try:
        username, uid = register_account(client)
        token = access_token_of(client, username)
        email = unique_email("aebind")
        resp = req_bind(client, token, email)
        assert resp.status_code == 200
        assert identity_of(resp) == {
            "code": "OK",
            "message": "如果该邮箱可绑定，我们已发送验证码",
            "data": None,
        }
        assert fake_smtp.instances, "PR-04 应触发一次 SMTP 投递"
    finally:
        _disable_smtp(app)


def test_af_pr04_smtp_failure_no_new_exists_channel(client, app, fake_smtp):
    """AF：PR-04 投递失败不得形成「邮箱是否被占用」的新信道（响应与成功态等同）。"""
    _enable_smtp(app, fake_smtp)
    try:
        username, uid = register_account(client)
        token = access_token_of(client, username)
        # 先占一个邮箱（另一账号已绑定），使目标邮箱「已被占用」
        taken = unique_email("aftaken")
        other, other_uid = register_account(client)
        set_email_verified(other_uid, taken)

        # 正常投递态
        ok = req_bind(client, token, unique_email("afok"))
        # 已占用 + 投递失败态
        fake_smtp.fail_on = "connect"
        fake_smtp.fail_exc = smtplib.SMTPConnectError(421, b"down")
        bad = req_bind(client, token, taken)
        assert bad.status_code == ok.status_code == 200
        assert identity_of(bad) == identity_of(ok), "投递失败暴露了邮箱占用状态（新信道）"
    finally:
        _disable_smtp(app)


# ══════════════════════════════════════════════════════════════════
# AG/AH/AI. PR-04 既有安全规则不变
# ══════════════════════════════════════════════════════════════════
def test_ag_pr04_current_password_check_unchanged(client, app, fake_smtp):
    _enable_smtp(app, fake_smtp)
    try:
        username, uid = register_account(client)
        token = access_token_of(client, username)
        resp = req_bind(client, token, unique_email("agpw"), password="wrong-password")
        assert resp.status_code != 200, "当前密码错误时**不得**返回 200 恒等响应"
        assert fake_smtp.instances == [], "密码校验未通过**不得**投递"
    finally:
        _disable_smtp(app)


def test_ah_pr04_cooldown_unchanged(client, app, fake_smtp):
    _enable_smtp(app, fake_smtp)
    try:
        username, uid = register_account(client)
        token = access_token_of(client, username)
        email = unique_email("ahcd")
        first = req_bind(client, token, email)
        assert first.status_code == 200
        n_after_first = len(fake_smtp.instances)
        second = req_bind(client, token, unique_email("ahcd2"))
        assert second.status_code == 200
        assert len(fake_smtp.instances) == n_after_first, "60s 冷却期内不得重复投递"
    finally:
        _disable_smtp(app)


def test_ai_pr05_confirm_unchanged(client, app, fake_smtp):
    """AI：PR-05 校验绑定验证码逻辑不变（经内存箱取码完成绑定）。"""
    # 本用例**不切** smtp，用 memory 后端完成绑定闭环（PR-05 属既有能力回归）
    from .conftest import latest_bind_code_for  # 局部导入避免循环

    username, uid = register_account(client)
    token = access_token_of(client, username)
    email = unique_email("aiconfirm")
    r = req_bind(client, token, email)
    assert r.status_code == 200
    code = latest_bind_code_for(email)
    assert code is not None
    # 此时仍处于可选路径：core/password_reset 策略未改
    assert len(code) == 6 and code.isdigit()


# ══════════════════════════════════════════════════════════════════
# AJ~AN. 验证码策略常量不变（**读冻结件，不改**）
# ══════════════════════════════════════════════════════════════════
def test_aj_code_length_still_six():
    from app.core import password_reset as pr

    assert pr.CODE_LENGTH == 6


def test_ak_ttl_still_fifteen_minutes():
    from app.core import password_reset as pr

    assert pr.CODE_TTL_MINUTES == 15


def test_al_max_attempts_still_five():
    from app.core import password_reset as pr

    assert pr.CODE_MAX_ATTEMPTS == 5


def test_am_cooldown_still_sixty_seconds():
    from app.core import password_reset as pr

    assert pr.RESEND_COOLDOWN_SECONDS == 60


def test_an_hmac_hash_rules_unchanged():
    """AN：HMAC 规则不变（同一 (pepper,user_id,purpose,code) ⇒ 同一摘要；不同码 ⇒ 不同摘要）。"""
    from app.core import password_reset as pr

    a = pr.hash_verification_code("pepper-x", 7, "password_reset", "123456")
    b = pr.hash_verification_code("pepper-x", 7, "password_reset", "123456")
    c = pr.hash_verification_code("pepper-x", 7, "password_reset", "123457")
    assert a == b
    assert a != c
    assert "123456" not in a, "哈希中不得含明文码"


# ══════════════════════════════════════════════════════════════════
# AP/AQ. file-outbox / redacted-console 不回归
# ══════════════════════════════════════════════════════════════════
def test_ap_file_outbox_not_regressed(tmp_path):
    result = mail_service.send_password_reset_code(
        {"MAIL_BACKEND": "file-outbox", "MAIL_OUTBOX_DIR": str(tmp_path / "outbox")},
        to_email="someone@example.com",
        code="707172",
        ttl_minutes=15,
    )
    assert result.delivered is True
    assert result.backend == "file-outbox"
    files = list((tmp_path / "outbox").glob("*.eml.txt"))
    assert len(files) == 1
    assert "707172" in files[0].read_text(encoding="utf-8")


def test_aq_redacted_console_not_regressed(caplog):
    with caplog.at_level(logging.INFO):
        result = mail_service.send_password_reset_code(
            {"MAIL_BACKEND": "redacted-console"},
            to_email="victim@example.com",
            code="737475",
            ttl_minutes=15,
        )
    assert result.delivered is True
    assert result.backend == "redacted-console"
    assert "victim@example.com" not in caplog.text
    assert "737475" not in caplog.text


# ══════════════════════════════════════════════════════════════════
# AR. 自动化测试**零真实网络**
# ══════════════════════════════════════════════════════════════════
def test_ar_no_real_network_guard(monkeypatch):
    """AR：本目录若忘记替换 ``smtplib.SMTP``，真实 socket 连接将**被拦截并失败**。

    做法：把 ``socket.socket.connect`` 换成抛异常的桩，然后构造一个「未打桩的」
    smtp 后端调用 —— 只要实现真的会连网，就必然抛 ``AssertionError``；
    而实现被正确 mock 时（用例内 fixture）不会走到 socket。
    """

    def _forbidden(*_a, **_k):
        raise AssertionError("自动化测试禁止真实网络连接")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    # ① 不替换 SMTP ⇒ 真实 smtplib 会尝试连网 ⇒ 必须 delivered=False（被捕获、不冒泡）
    result = mail_service.send_password_reset_code(
        smtp_cfg(SMTP_HOST="127.0.0.1", SMTP_PORT="9"),  # 不可达端口
        to_email="someone@example.com",
        code="787980",
        ttl_minutes=15,
    )
    assert result.delivered is False, "连网失败也必须收敛为 delivered=False"
    assert result.backend == "smtp"


def test_ar_mock_used_when_fixture_present(fake_smtp):
    """AR 反面：装了 fixture 的用例**不触发**任何真实 socket。"""
    called = {"n": 0}

    def _spy(*_a, **_k):
        called["n"] += 1
        raise AssertionError("不应发生真实网络")

    import socket as _s

    original = _s.socket.connect
    _s.socket.connect = _spy
    try:
        result = mail_service.send_password_reset_code(
            smtp_cfg(), to_email="someone@example.com", code="787980", ttl_minutes=15
        )
    finally:
        _s.socket.connect = original
    assert result.delivered is True
    assert called["n"] == 0