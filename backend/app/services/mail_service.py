# -*- coding: utf-8 -*-
"""找回密码 —— 邮件投递后端抽象（**B2**）。

依据
----
- ``CR-F006-001``（``F-006`` →「V1.0 发布前补齐功能」）
- 《忘记密码自助找回 · 开工前只读审计与方案报告》§七（邮件发送方案）
- 需求方 B2 授权 §十一「邮件基础设施边界」

本模块提供**可替换的后端抽象**与**消息组装**：

| 后端 | 取值 | 行为 | 本批 |
|---|---|---|---|
| 内存 | ``memory`` | 存入进程内列表（**测试与开发默认**，零文件副作用） | ✅ |
| 文件出件箱 | ``file-outbox`` | 追加写入 ``storage/mail_outbox/``（本地联调用，**默认不启用**） | ✅ |
| 脱敏控制台 | ``redacted-console`` | 只打印**不含任何真实值**的投递行 | ✅ |
| SMTP | ``smtp`` | **真实投递**（标准库 ``smtplib`` ＋ ``EmailMessage``） | ✅ |

⚠️ 硬边界（延续 B2/B3 冻结 ＋ MAIL-DELIVERY-1 授权）
1. **凭据只从运行时配置读取** —— ``SMTP_PASSWORD`` 等**绝不**硬编码、绝不落盘、
   绝不进入日志 / 异常对外文本 / API 响应 / DB。缺失或为占位符时 **fail-closed**
   （收敛为「未投递」，**不**静默降级、**不**假装已发送）。
2. **禁止**把邮箱 / 验证码写入**运行日志** —— ``redacted-console`` 与 ``smtp``
   成功行都只打印 ``***``；本模块**从不**把 ``to_email`` / ``code`` 传给 ``logger``。
3. ``memory`` / ``file-outbox`` 中保存的是**投递载荷**（邮件的等价物，非日志、
   非 artifacts）：``memory`` 仅存在于进程内、随进程结束消失；
   ``file-outbox`` 目录默认**不创建**（仅显式配置该后端时才建）。

调用约定：**投递失败绝不改变对外响应**（统一 200 恒等，见 PR-01 防枚举），
失败细节只以**脱敏**形式返回给调用方做服务端告警。
"""
from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.password_reset import PURPOSE_EMAIL_BIND, PURPOSE_PASSWORD_RESET

logger = logging.getLogger(__name__)

# ── 后端取值（冻结；与 `config.MAIL_BACKEND` 同一口径）────────────────────
BACKEND_MEMORY = "memory"
BACKEND_FILE_OUTBOX = "file-outbox"
BACKEND_REDACTED_CONSOLE = "redacted-console"
BACKEND_SMTP = "smtp"
SUPPORTED_BACKENDS: Tuple[str, ...] = (
    BACKEND_MEMORY,
    BACKEND_FILE_OUTBOX,
    BACKEND_REDACTED_CONSOLE,
    BACKEND_SMTP,
)
#: 缺省后端 = 内存（测试/开发零副作用）
DEFAULT_BACKEND = BACKEND_MEMORY

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = BACKEND_DIR / "app" / "templates" / "email" / "password_reset_code.txt"
#: **B3**：邮箱绑定验证码模板（与找回密码模板**分离** —— 措辞与用途不同）
BIND_TEMPLATE_PATH = BACKEND_DIR / "app" / "templates" / "email" / "email_bind_code.txt"
#: 出件箱子目录（相对 ``storage/``；**默认不创建**）
OUTBOX_SUBDIR = "mail_outbox"

#: 邮件主题（**不含任何账号标识**）
SUBJECT_PASSWORD_RESET = "找回密码验证码"
#: **B3**：邮箱绑定邮件主题（同样**不含任何账号标识**）
SUBJECT_EMAIL_BIND = "邮箱绑定验证码"
#: 发件人显示名（未配置 SMTP 时仅为占位文案，不进任何真实投递）
DEFAULT_FROM_LABEL = "HealthTrack"

#: 进程内投递箱（``memory`` 后端；随进程结束消失）
_memory_outbox: List[Dict[str, Any]] = []


@dataclass(frozen=True)
class DeliveryResult:
    """投递结果。``detail`` **绝不含**邮箱或验证码。"""

    delivered: bool
    backend: str
    detail: str = ""


# ══════════════════════════════════════════════════════════════════
# 后端解析与消息组装
# ══════════════════════════════════════════════════════════════════
def resolve_backend(cfg: Optional[Dict[str, Any]]) -> str:
    """取当前邮件后端；未配置 / 非法值 → ``memory``（**不静默落到 smtp**）。"""
    raw = str((cfg or {}).get("MAIL_BACKEND") or "").strip().lower()
    return raw if raw in SUPPORTED_BACKENDS else DEFAULT_BACKEND


def load_template() -> str:
    """读取纯文本模板（**不引 HTML 模板引擎**）。"""
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def load_bind_template() -> str:
    """读取**邮箱绑定**纯文本模板（**B3**；与找回密码模板分离）。"""
    return BIND_TEMPLATE_PATH.read_text(encoding="utf-8")


def render_template(template: str, values: Dict[str, str]) -> str:
    """极简占位替换（``{{key}}``）。

    ⚠️ 刻意**不用** ``str.format``：模板正文含中文与换行，且 ``{}`` 语义
    容易与未来模板内容冲突；``replace`` 的失败模式是「原样保留」而非抛异常。
    """
    out = template
    for key, value in values.items():
        out = out.replace("{{%s}}" % key, str(value))
    return out


def build_reset_code_message(
    *, code: str, ttl_minutes: int, app_name: str = DEFAULT_FROM_LABEL
) -> Tuple[str, str]:
    """组装 ``(subject, body)``。**返回值含验证码 ⇒ 调用方不得写入日志。**"""
    body = render_template(
        load_template(),
        {"app_name": str(app_name), "code": str(code), "ttl_minutes": str(int(ttl_minutes))},
    )
    return SUBJECT_PASSWORD_RESET, body


def build_email_bind_message(
    *, code: str, ttl_minutes: int, app_name: str = DEFAULT_FROM_LABEL
) -> Tuple[str, str]:
    """**B3**：组装邮箱绑定 ``(subject, body)``。

    **返回值含验证码 ⇒ 调用方不得写入日志。**
    """
    body = render_template(
        load_bind_template(),
        {"app_name": str(app_name), "code": str(code), "ttl_minutes": str(int(ttl_minutes))},
    )
    return SUBJECT_EMAIL_BIND, body


# ══════════════════════════════════════════════════════════════════
# 内存后端（测试读取用）
# ══════════════════════════════════════════════════════════════════
def memory_outbox() -> List[Dict[str, Any]]:
    """当前进程内投递箱（**只读快照**；测试断言用）。"""
    return list(_memory_outbox)


def drain_memory_outbox() -> List[Dict[str, Any]]:
    """清空并返回进程内投递箱（测试 teardown 用；避免跨用例串味）。"""
    items = list(_memory_outbox)
    _memory_outbox.clear()
    return items


# ══════════════════════════════════════════════════════════════════
# 各后端实现
# ══════════════════════════════════════════════════════════════════
def _send_memory(
    *, to_email: str, subject: str, body: str, code: str,
    purpose: str = PURPOSE_PASSWORD_RESET,
) -> DeliveryResult:
    """进程内投递箱。

    ``purpose`` 为 **B3 追加**（默认 ``password_reset`` ⇒ 既有调用行为逐字不变）；
    仅用于测试区分「这条投递载荷属于哪个用途」，**不落库、不进日志**。
    """
    _memory_outbox.append(
        {
            "to": str(to_email),
            "subject": str(subject),
            "body": str(body),
            "code": str(code),
            "purpose": str(purpose),
            "sent_at": datetime.now().replace(microsecond=0),
        }
    )
    return DeliveryResult(True, BACKEND_MEMORY, "已存入内存投递箱")


def _outbox_dir(cfg: Optional[Dict[str, Any]]) -> Path:
    raw = str((cfg or {}).get("MAIL_OUTBOX_DIR") or "").strip()
    base = Path(raw) if raw else (BACKEND_DIR / "storage" / OUTBOX_SUBDIR)
    if not base.is_absolute():
        base = BACKEND_DIR / base
    return base


def _send_file_outbox(
    *, cfg: Optional[Dict[str, Any]], to_email: str, subject: str, body: str
) -> DeliveryResult:
    """写文件出件箱（**本地联调**；目录按需创建，失败不影响对外响应）。"""
    try:
        target_dir = _outbox_dir(cfg)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = target_dir / f"{stamp}.eml.txt"
        # 出件箱文件 = 邮件等价物（含收件人与正文），**不是日志**
        path.write_text(
            f"To: {to_email}\nSubject: {subject}\n\n{body}\n", encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 —— 投递失败不改变对外响应
        return DeliveryResult(False, BACKEND_FILE_OUTBOX, f"出件箱写入失败（{type(exc).__name__}）")
    return DeliveryResult(True, BACKEND_FILE_OUTBOX, "已写入文件出件箱")


def _send_redacted_console(*, to_email: str, code: str) -> DeliveryResult:
    """只打印**脱敏**投递行 —— 不含邮箱、不含验证码。"""
    logger.info(
        "[mail] backend=%s 投递=%s to=%s code=%s",
        BACKEND_REDACTED_CONSOLE,
        "OK",
        "***",
        "***",
    )
    return DeliveryResult(True, BACKEND_REDACTED_CONSOLE, "已打印脱敏投递行")


# ══════════════════════════════════════════════════════════════════
# SMTP 配置解析（**全部 fail-closed**：缺 / 非法 ⇒ 拒绝投递，绝不猜）
# ══════════════════════════════════════════════════════════════════
#: SMTP 默认值（授权 §三）
SMTP_DEFAULT_HOST = "smtp.gmail.com"
SMTP_DEFAULT_PORT = 587
SMTP_DEFAULT_USE_TLS = True
SMTP_DEFAULT_TIMEOUT = 10

#: 明确布尔真值 / 假值集合（**禁止 bool("false") 陷阱**）
_TLS_TRUE = ("1", "true", "yes", "on", "y", "t")
_TLS_FALSE = ("0", "false", "no", "off", "n", "f")


class SmtpConfigError(ValueError):
    """SMTP 配置缺失 / 非法。**对外不抛出** —— 由 :func:`_send_smtp` 收敛为未投递。"""


def _smtp_text(cfg: Dict[str, Any], key: str) -> str:
    """取一个字符串配置项；占位符 / 空白视同未配置。"""
    raw = (cfg or {}).get(key)
    if raw is None:
        return ""
    text = str(raw).strip()
    return "" if _is_placeholder(text) else text


def _is_placeholder(value: str) -> bool:
    """与 ``core/config.py::_is_placeholder`` 同口径：空 / 含 ``CHANGE_ME``。"""
    text = str(value).strip()
    return text == "" or "CHANGE_ME" in text.upper()


def _parse_use_tls(cfg: Dict[str, Any]) -> bool:
    """**显式**布尔解析：无法明确判定为真/假 ⇒ 抛 :class:`SmtpConfigError`。"""
    raw = (cfg or {}).get("SMTP_USE_TLS")
    if raw is None or str(raw).strip() == "":
        return SMTP_DEFAULT_USE_TLS
    token = str(raw).strip().lower()
    if token in _TLS_TRUE:
        return True
    if token in _TLS_FALSE:
        return False
    raise SmtpConfigError("SMTP_USE_TLS 取值无法解析为布尔")


def _parse_port(cfg: Dict[str, Any]) -> int:
    raw = (cfg or {}).get("SMTP_PORT")
    if raw is None or str(raw).strip() == "":
        return SMTP_DEFAULT_PORT
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise SmtpConfigError("SMTP_PORT 非整数") from exc
    if not (1 <= port <= 65535):
        raise SmtpConfigError("SMTP_PORT 超出范围")
    return port


def _parse_timeout(cfg: Dict[str, Any]) -> float:
    """超时：非法值**回落默认**（配置瑕疵不应阻断投递），但必须为正数。"""
    raw = (cfg or {}).get("SMTP_TIMEOUT")
    if raw is None or str(raw).strip() == "":
        return float(SMTP_DEFAULT_TIMEOUT)
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return float(SMTP_DEFAULT_TIMEOUT)
    if value <= 0:
        return float(SMTP_DEFAULT_TIMEOUT)
    return value


def _resolve_sender(cfg: Dict[str, Any]) -> Tuple[str, str, str, str, int, float, bool]:
    """解析 SMTP 配置并**校验必需项**；返回 ``(host, user, password, sender, ...)``。

    ``SMTP_FROM`` 未配置 ⇒ **回落** ``SMTP_USERNAME``（二者皆缺 ⇒ fail-closed）。
    """
    host = _smtp_text(cfg, "SMTP_HOST")
    if not host:
        raise SmtpConfigError("SMTP_HOST 缺失")
    username = _smtp_text(cfg, "SMTP_USERNAME")
    if not username:
        raise SmtpConfigError("SMTP_USERNAME 缺失")
    password = _smtp_text(cfg, "SMTP_PASSWORD")
    if not password:
        raise SmtpConfigError("SMTP_PASSWORD 缺失")
    sender = _smtp_text(cfg, "SMTP_FROM") or username  # 未配置 From ⇒ 回落用户名
    port = _parse_port(cfg)
    timeout = _parse_timeout(cfg)
    use_tls = _parse_use_tls(cfg)
    return host, username, password, sender, port, timeout, use_tls


def _build_smtp_message(*, sender: str, to_email: str, subject: str, body: str) -> EmailMessage:
    """构造纯文本 ``EmailMessage``（From/To/Subject 与既有模板语义一致）。"""
    msg = EmailMessage()
    msg["From"] = formataddr((DEFAULT_FROM_LABEL, sender))
    msg["To"] = str(to_email)
    msg["Subject"] = str(subject)
    msg.set_content(str(body))
    return msg


def _smtp_failure_detail(stage: str, exc: BaseException) -> str:
    """**脱敏**失败说明：只给「阶段 ＋ 异常类别」，**绝不**回传 exception repr。

    ⚠️ ``smtplib`` 的异常 repr 可能包含服务器原文 / 账号线索 / 凭据片段，
    因此这里**只取类型名**，不拼接 ``str(exc)``。
    """
    return f"SMTP {stage} 失败（{type(exc).__name__}）"


def _send_smtp(
    *, cfg: Optional[Dict[str, Any]], to_email: str, subject: str, body: str
) -> DeliveryResult:
    """真实 SMTP 投递（标准库 ``smtplib`` ＋ ``EmailMessage``）。

    链路（TLS 开启时）：连接 → ``ehlo`` → ``starttls`` → ``ehlo`` → ``login`` →
    ``send_message`` → 关闭（``with`` 保障）。

    **绝不抛异常**：配置缺失 / 连接 / TLS / 认证 / 发送 / 超时 / 其他异常
    一律收敛为 ``DeliveryResult(False, BACKEND_SMTP, <脱敏阶段说明>)``。
    """
    try:
        host, username, password, sender, port, timeout, use_tls = _resolve_sender(cfg or {})
    except SmtpConfigError as exc:
        return DeliveryResult(False, BACKEND_SMTP, f"SMTP 配置不可用（{exc}）")

    try:
        message = _build_smtp_message(
            sender=sender, to_email=to_email, subject=subject, body=body
        )
    except Exception as exc:  # noqa: BLE001 —— 组装失败同样不得冒泡
        return DeliveryResult(False, BACKEND_SMTP, _smtp_failure_detail("组装", exc))

    smtp = None
    try:
        # 使用上下文管理器 ⇒ 任何分支都会关闭连接（授权 §五）
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if use_tls:
                try:
                    smtp.starttls()
                except Exception as exc:  # noqa: BLE001
                    return DeliveryResult(False, BACKEND_SMTP, _smtp_failure_detail("TLS", exc))
                smtp.ehlo()
            try:
                smtp.login(username, password)
            except Exception as exc:  # noqa: BLE001
                return DeliveryResult(False, BACKEND_SMTP, _smtp_failure_detail("认证", exc))
            try:
                smtp.send_message(message)
            except Exception as exc:  # noqa: BLE001
                return DeliveryResult(False, BACKEND_SMTP, _smtp_failure_detail("发送", exc))
    except Exception as exc:  # noqa: BLE001 —— 连接 / 超时 / 其他
        return DeliveryResult(False, BACKEND_SMTP, _smtp_failure_detail("连接", exc))

    logger.info(
        "[mail] backend=%s 投递=%s to=%s code=%s",
        BACKEND_SMTP,
        "OK",
        "***",  # 收件邮箱**脱敏**（复用 redacted-console 口径，不新增完整邮箱日志）
        "***",
    )
    return DeliveryResult(True, BACKEND_SMTP, "SMTP 投递成功")


# ══════════════════════════════════════════════════════════════════
# 统一入口
# ══════════════════════════════════════════════════════════════════
def send_password_reset_code(
    cfg: Optional[Dict[str, Any]],
    *,
    to_email: str,
    code: str,
    ttl_minutes: int,
    app_name: str = DEFAULT_FROM_LABEL,
) -> DeliveryResult:
    """按配置后端投递验证码邮件。

    **绝不抛异常**：任何后端失败都以 ``DeliveryResult(delivered=False)`` 返回，
    由调用方决定是否做服务端脱敏告警 —— **不得**据此改变对外统一响应。
    """
    backend = resolve_backend(cfg)
    subject, body = build_reset_code_message(code=code, ttl_minutes=ttl_minutes, app_name=app_name)
    try:
        if backend == BACKEND_MEMORY:
            return _send_memory(
                to_email=to_email, subject=subject, body=body, code=code,
                purpose=PURPOSE_PASSWORD_RESET,
            )
        if backend == BACKEND_FILE_OUTBOX:
            return _send_file_outbox(
                cfg=cfg, to_email=to_email, subject=subject, body=body
            )
        if backend == BACKEND_REDACTED_CONSOLE:
            return _send_redacted_console(to_email=to_email, code=code)
        if backend == BACKEND_SMTP:
            return _send_smtp(cfg=cfg, to_email=to_email, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001 —— 兜底：投递层永不影响业务响应
        return DeliveryResult(False, backend, f"投递异常（{type(exc).__name__}）")
    return DeliveryResult(False, backend, "未知后端")


def send_email_bind_code(
    cfg: Optional[Dict[str, Any]],
    *,
    to_email: str,
    code: str,
    ttl_minutes: int,
    app_name: str = DEFAULT_FROM_LABEL,
) -> DeliveryResult:
    """**B3**：按配置后端投递**邮箱绑定**验证码邮件。

    与找回密码**共享同一后端集合与同一安全边界**：
    - 缺省 ``memory``（进程内，零文件副作用）；
    - ``smtp`` 沿用 B2 冻结的**占位、恒不投递、不读 ``SMTP_*``** 边界（本批不接真实 SMTP）；
    - **绝不抛异常**；**绝不把邮箱 / 验证码写入日志**。
    """
    backend = resolve_backend(cfg)
    subject, body = build_email_bind_message(
        code=code, ttl_minutes=ttl_minutes, app_name=app_name
    )
    try:
        if backend == BACKEND_MEMORY:
            return _send_memory(
                to_email=to_email, subject=subject, body=body, code=code,
                purpose=PURPOSE_EMAIL_BIND,
            )
        if backend == BACKEND_FILE_OUTBOX:
            return _send_file_outbox(cfg=cfg, to_email=to_email, subject=subject, body=body)
        if backend == BACKEND_REDACTED_CONSOLE:
            return _send_redacted_console(to_email=to_email, code=code)
        if backend == BACKEND_SMTP:
            return _send_smtp(cfg=cfg, to_email=to_email, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001 —— 兜底：投递层永不影响业务响应
        return DeliveryResult(False, backend, f"投递异常（{type(exc).__name__}）")
    return DeliveryResult(False, backend, "未知后端")


__all__ = [
    "BACKEND_MEMORY",
    "BACKEND_FILE_OUTBOX",
    "BACKEND_REDACTED_CONSOLE",
    "BACKEND_SMTP",
    "SUPPORTED_BACKENDS",
    "DEFAULT_BACKEND",
    "OUTBOX_SUBDIR",
    "SUBJECT_PASSWORD_RESET",
    "SUBJECT_EMAIL_BIND",
    "BIND_TEMPLATE_PATH",
    "SMTP_DEFAULT_HOST",
    "SMTP_DEFAULT_PORT",
    "SMTP_DEFAULT_USE_TLS",
    "SMTP_DEFAULT_TIMEOUT",
    "SmtpConfigError",
    "DeliveryResult",
    "resolve_backend",
    "load_template",
    "load_bind_template",
    "render_template",
    "build_reset_code_message",
    "build_email_bind_message",
    "memory_outbox",
    "drain_memory_outbox",
    "send_password_reset_code",
    "send_email_bind_code",
]
