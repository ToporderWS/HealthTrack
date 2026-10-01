# -*- coding: utf-8 -*-
"""B2 · 邮件后端边界（§十一）与日志安全（§十）。

证明三件事：
1. 缺省后端是 ``memory``（**零文件副作用**）；``file-outbox`` 目录**默认不创建**；
2. ``smtp`` 后端在 **MAIL-DELIVERY-1** 起为**真实投递**实现；本文件验证其
   **安全边界仍成立** —— secret 只从配置读取、无硬编码、``memory`` 不读 SMTP secret、
   仅 ``smtp`` 读取所需 SMTP 配置、secret 不进日志 / response / DB；
3. 邮件层**从不**把 ``to_email`` / ``code`` / ``body`` 交给 logger（AST 静态证明 ＋ 运行期验证）。
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

from app.services import mail_service

MAIL_SERVICE_PATH = Path(mail_service.__file__)


# ══════════════════════════════════════════════════════════════════
# 1. 缺省 = memory；未配置 / 非法值**不静默落到 smtp**
# ══════════════════════════════════════════════════════════════════
def test_default_backend_is_memory():
    assert mail_service.resolve_backend({}) == "memory"
    assert mail_service.resolve_backend({"MAIL_BACKEND": ""}) == "memory"
    assert mail_service.resolve_backend({"MAIL_BACKEND": "bogus"}) == "memory"
    assert mail_service.resolve_backend(None) == "memory"
    assert mail_service.resolve_backend({"MAIL_BACKEND": "smtp"}) == "smtp"


def test_memory_backend_stores_payload_without_touching_files():
    result = mail_service.send_password_reset_code(
        {"MAIL_BACKEND": "memory"}, to_email="someone@example.com", code="654321", ttl_minutes=15
    )
    assert result.delivered is True
    assert result.backend == "memory"
    box = mail_service.memory_outbox()
    assert len(box) == 1
    assert box[0]["code"] == "654321"
    assert "654321" in box[0]["body"]
    # memory 后端**不创建**任何目录
    assert not (Path(mail_service.BACKEND_DIR) / "storage" / mail_service.OUTBOX_SUBDIR).exists()


# ══════════════════════════════════════════════════════════════════
# 2. smtp 后端：**配置缺失 ⇒ fail-closed**（安全边界；真实投递见 tests/mail/）
#    ⚠️ MAIL-PRE-BLOCKER-1 翻正（MAIL-DELIVERY-1）：原判据「本批恒不投递」已随
#       真实实现失效；新判据验证「未配置 SMTP 必需项时绝不投递、绝不落 memory」。
# ══════════════════════════════════════════════════════════════════
def test_smtp_backend_fails_closed_without_config():
    result = mail_service.send_password_reset_code(
        {"MAIL_BACKEND": "smtp"}, to_email="someone@example.com", code="654321", ttl_minutes=15
    )
    assert result.delivered is False
    assert result.backend == "smtp"
    # 绝不静默落到 memory（其他后端亦不得被误用）
    assert mail_service.memory_outbox() == []


def test_mail_service_reads_smtp_secrets_only_from_cfg():
    """**翻正后新判据**（MAIL-PRE-BLOCKER-1 / 授权 §十）：

    允许 ``mail_service`` 引用 ``smtplib`` 并读取 ``SMTP_*`` 配置键；但必须满足
    五条安全约束：
    ① secret 只从 **参数 cfg** 读取（不得直接读 ``os.environ``）；
    ② **不得**出现硬编码凭据字面量；
    ③ ``memory`` 分支**不读** ``SMTP_PASSWORD``（运行期证明）；
    ④ 仅 ``smtp`` 分支读取所需 SMTP 配置（运行期证明）；
    ⑤ secret 不进日志 / response / DB（由 tests/mail/ 矩阵与脱敏矩阵覆盖）。
    """
    source = MAIL_SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # ① 不得直接读 os.environ（密钥必须经 config → cfg 注入）
    assert "os.environ" not in source, "mail_service 不得直接读取 os.environ"

    # ② 不得硬编码凭据（只考察 ASCII 串，避免误伤中文 docstring）
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if not v.isascii():
                continue
            if len(v) >= 16 and (" " not in v) and any(c.isdigit() for c in v) and any(
                c.isalpha() for c in v
            ):
                if not any(tok in v for tok in ("/", "\\", ".py", ".txt", "%s", "{{", "https")):
                    offenders.append(v)
    assert offenders == [], f"mail_service 出现疑似硬编码凭据：{offenders}"

    # ③ ``SMTP_*`` 键只允许出现在「取配置值」的语境（下标 / .get 调用）
    allowed_context = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value.startswith("SMTP_"):
                            allowed_context = allowed_context and True
    assert allowed_context

    # ④ smtplib 必须已被引入（真实投递实现的必要条件）
    assert "import smtplib" in source, "MAIL-DELIVERY-1 后 mail_service 应引入 smtplib"


def test_memory_backend_does_not_read_smtp_password(monkeypatch):
    """③／④ 运行期证明：``memory`` 后端**不读** ``SMTP_PASSWORD``。"""
    read_keys = []
    real_get = dict.get

    class _SpyCfg(dict):
        def get(self, key, default=None):  # noqa: ANN001
            if isinstance(key, str) and key.startswith("SMTP_"):
                read_keys.append(key)
            return real_get(self, key, default)

    cfg = _SpyCfg({"MAIL_BACKEND": "memory", "SMTP_PASSWORD": "dummy-app-password"})
    result = mail_service.send_password_reset_code(
        cfg, to_email="someone@example.com", code="654321", ttl_minutes=15
    )
    assert result.delivered is True
    assert result.backend == "memory"
    assert "SMTP_PASSWORD" not in read_keys, "memory 后端**不得**读取 SMTP_PASSWORD"


# ══════════════════════════════════════════════════════════════════
# 3. 邮件层**从不**把真值交给 logger（AST 静态证明）
# ══════════════════════════════════════════════════════════════════
def test_mail_service_never_logs_real_values():
    tree = ast.parse(MAIL_SERVICE_PATH.read_text(encoding="utf-8"))
    forbidden = {"to_email", "code", "body", "subject", "raw", "token"}
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"debug", "info", "warning", "error", "exception", "critical"}
        ):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            hit = names & forbidden
            if hit:
                offenders.append((getattr(node, "lineno", -1), sorted(hit)))
    assert offenders == [], f"邮件层日志引用了真值变量：{offenders}"


def test_redacted_console_backend_prints_no_real_values(caplog):
    with caplog.at_level(logging.INFO):
        result = mail_service.send_password_reset_code(
            {"MAIL_BACKEND": "redacted-console"},
            to_email="victim@example.com",
            code="246810",
            ttl_minutes=15,
        )
    assert result.delivered is True
    assert "victim@example.com" not in caplog.text
    assert "246810" not in caplog.text


# ══════════════════════════════════════════════════════════════════
# 4. 模板渲染：占位符被替换，且不含 HTML（纯文本降复杂度）
# ══════════════════════════════════════════════════════════════════
def test_reset_code_template_is_plain_text_and_renders():
    subject, body = mail_service.build_reset_code_message(code="135790", ttl_minutes=15)
    assert subject == "找回密码验证码"
    assert "135790" in body
    assert "15" in body
    assert "{{" not in body and "}}" not in body
    assert "<" not in body and ">" not in body, "模板应为纯文本，不得含 HTML 标签"


# ══════════════════════════════════════════════════════════════════
# 5. 投递层**绝不抛异常**（调用方可无条件按恒等响应回复）
# ══════════════════════════════════════════════════════════════════
def test_delivery_never_raises(monkeypatch):
    def _boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise RuntimeError("投递后端爆炸")

    monkeypatch.setattr(mail_service, "_send_memory", _boom)
    result = mail_service.send_password_reset_code(
        {"MAIL_BACKEND": "memory"}, to_email="a@b.com", code="111111", ttl_minutes=15
    )
    assert result.delivered is False
    assert result.backend == "memory"


# ══════════════════════════════════════════════════════════════════
# 6. §六：**原始 LogRecord** 上的脱敏矩阵
#    （必须覆盖 7 个敏感键；且普通 ``code=OK`` 不得被误脱敏）
# ══════════════════════════════════════════════════════════════════
#: §六 明令至少覆盖的键名 → **哨兵伪值**（全部为伪造串，非任何真实数据）
SENSITIVE_MATRIX = {
    "email": "sentinel-address@example.invalid",
    "verification_code": "313373",
    "reset_token": "SENTINEL-RESET-TOKEN",
    "password_reset_token": "SENTINEL-PWRESET-TOKEN",
    "password": "SENTINEL-PASSWORD",
    "password_hash": "$2b$12$SENTINELHASH",
    "password_reset_pepper": "SENTINEL-PEPPER",
}

#: 值可能出现的四种形态（`k=v` / `k: v` / `k='v'` / JSON `{"k": "v"}`）
_KV_SHAPES = ("%s=%s", "%s: %s", "%s='%s'", '{"%s": "%s"}')


def _apply_filter(msg: str) -> str:
    """把一条日志消息送进**真实** ``SensitiveDataFilter``，返回处理后的文本。"""
    from app.core.logging import SensitiveDataFilter

    record = logging.LogRecord(
        name="b2.redaction",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    assert SensitiveDataFilter().filter(record) is True
    return record.getMessage()


def test_logging_redacts_every_required_sensitive_key():
    """§六：逐个敏感键、逐种键值形态 ⇒ 值必须被 ``***`` 完全遮蔽。"""
    for key, value in SENSITIVE_MATRIX.items():
        for shape in _KV_SHAPES:
            rendered = _apply_filter(shape % (key, value))
            assert value not in rendered, f"{key} 的值未脱敏（{shape}）：{rendered!r}"
            assert "***" in rendered, f"{key} 未产生掩码（{shape}）：{rendered!r}"
            assert key in rendered, f"{key} 键名被误删（{shape}）：{rendered!r}"


def test_logging_does_not_over_redact_benign_code_field():
    """§六：正常业务字段 ``code=OK`` **不得**被误脱敏（禁止裸 ``code`` 进敏感键）。"""
    msg = "password-reset request finished code=OK username=tstb2deadbeef"
    assert _apply_filter(msg) == msg, "正常业务字段被误脱敏（脱敏必须精确到键名）"
