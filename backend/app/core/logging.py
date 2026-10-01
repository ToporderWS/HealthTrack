# -*- coding: utf-8 -*-
"""日志配置与隐私脱敏。

依据：
- 《S1-D-技术方案最终冻结》技术架构（logging 标准库；**不引入日志聚合组件**）
- 《S1-B 第二批 API 接口设计文档》§3.7 / 15.6：日志**不得**记录
  完整 username、``user_id``、密码、JWT、refresh token、数据库密码，
  亦不得记录可识别个人信息的真实文件路径。
- 《S1-A-安全规则冻结清单》文末「变更登记（``CR-F006-001`` · 2026-09-23）」：
  ``SR-1``~``SR-4``（验证码 / ``reset token`` **不得明文入库、不得进入日志**）、
  ``SR-13``（**邮箱 / 验证码 / ``reset token`` 必须纳入日志脱敏体系**）。

⚠️ 本模块的**实施前安全前置**（``CR-F006-001``）：
在任何验证码 / ``reset token`` 真正进入 HTTP 请求与日志链路**之前**，本脱敏体系
必须已覆盖以下字段（2026-09-23 **B1** 批已完成并独立验证）——
``email`` / ``verification_code`` / ``reset_token`` / ``password_reset_token`` /
``access_token`` / ``refresh_token`` / ``password`` / ``password_hash`` / ``smtp_password``
（另含 ``code_hash`` / ``token_hash`` 等**凭证等价物**，见 :data:`_SENSITIVE_KEYS`）。

注意：``LOG_RETENTION_DAYS`` 默认 180 天，**I-05「运行日志 6 个月保留」仍待法律/合规审核**，
      将来定稿后仅需调整配置，无需改代码。
"""
from __future__ import annotations

import logging
import os
import re
import time
from logging.handlers import TimedRotatingFileHandler

from flask import Flask, g, request

#: 需要脱敏的键名（键值对形式出现时）。
#:
#: ⚠️ **词边界陷阱 —— 复合键名必须逐条枚举**（``CR-F006-001`` 实测）：
#: :data:`_KV_PATTERN` 用 ``\b`` 定界，而 ``_`` 属**词字符**，因此
#: ``token`` **匹配不到** ``reset_token=``、``password`` **匹配不到**
#: ``password_reset_token=``（它们前面是词字符 ⇒ 不构成词边界）。
#: 故凡含下划线的复合键名一律显式列出，**不得寄望于前缀键覆盖**。
#:
#: ⚠️ **禁止**加入裸 ``code``：会误伤 ``code=OK`` / ``code=NOT_FOUND`` 等
#: 正常业务字段（脱敏必须精确到键名，不得按子串命中）。
_SENSITIVE_KEYS = (
    # ── 认证与令牌（既有）────────────────────────────────
    "password",
    "passwd",
    "pwd",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "secret_key",
    "jwt",
    # ── 找回密码 / 邮箱（CR-F006-001 · SR-13，2026-09-23 B1）──
    #    含「凭证等价物」（hash）—— 6 位验证码的哈希与明文等价（可离线爆破），
    #    故 code_hash / token_hash 亦必须纳入脱敏。
    "email",
    "verification_code",
    "verification_code_hash",
    "code_hash",
    "reset_token",
    "reset_token_hash",
    "password_reset_token",
    "password_reset_token_hash",
    "token_hash",
    "access_token_hash",
    "refresh_token_hash",
    "smtp_password",
    "password_reset_pepper",
)

#: 一个「值」的形态：**优先**匹配被引号包裹的值（JSON / dict repr），
#: 否则退回裸值（M1 保留原字符集 ``[^\s,;\"'}]+``，行为与改动前逐字符一致）。
_VALUE_RE = r"""(?:"[^"]*"|'[^']*'|[^\s,;\"'}]+)"""

_KV_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(_SENSITIVE_KEYS) + r")\b(\"?\s*[:=]\s*)(" + _VALUE_RE + r")"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_USERID_PATTERN = re.compile(r"(?i)\b(user_id|userId)\b\s*[:=]\s*\d+")


def _mask_kv(match) -> str:  # noqa: ANN001
    """把 ``键 <分隔符> 值`` 掩码为 ``键 <分隔符> ***``（**保留原分隔符与引号形态**）。

    - ``email=a@b.com``      → ``email=***``
    - ``{"email": "a@b"}``   → ``{"email": "***"}``（仍是合法 JSON）
    - ``reset_token: 'xx'``  → ``reset_token: '***'``

    ⚠️ **统一规则 = 完全 REDACTED（``***``），不做部分掩码**
    （不做 ``a***@b.com`` 之类局部保留）：① 与既有 ``f"{k}=***"`` 语义一致；
    ② 部分掩码仍属**可识别个人信息**（local-part 泄露即已可关联账号）；
    ③ 找回流程的排障以 ``request_id`` 为主键，不以邮箱可读性为刚需。
    """
    value = match.group(3)
    quote = value[0] if value[:1] in ('"', "'") else ""
    return f"{match.group(1)}{match.group(2)}{quote}***{quote}"


class SensitiveDataFilter(logging.Filter):
    """在日志落盘前遮蔽敏感值（**宁多掩不漏**）。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.getMessage()
        except Exception:
            return True
        message = _KV_PATTERN.sub(_mask_kv, message)
        message = _BEARER_PATTERN.sub("Bearer ***", message)
        message = _USERID_PATTERN.sub(lambda m: f"{m.group(1)}=***", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(app: Flask) -> None:
    """配置应用日志（控制台 + 按天轮转文件）。"""
    level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    log_dir = app.config.get("LOG_DIR") or "./logs"
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    scrub = SensitiveDataFilter()

    root = logging.getLogger()
    root.setLevel(level)
    # 避免重复添加 handler（如测试中多次 create_app）
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(scrub)
    root.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        when="midnight",
        backupCount=int(app.config.get("LOG_RETENTION_DAYS", 180)),
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(scrub)
    root.addHandler(file_handler)

    # 降低第三方库噪音
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.before_request
    def _mark_start():  # noqa: ANN202
        g._req_started_at = time.perf_counter()

    @app.after_request
    def _log_request(response):  # noqa: ANN001, ANN202
        started = getattr(g, "_req_started_at", None)
        duration_ms = (time.perf_counter() - started) * 1000 if started else -1
        # 只记录 method + path（不含 query string）+ 状态 + request_id + 耗时；
        # 不记录 user_id / 用户名 / 健康数值
        app.logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            # 去掉查询串，避免把参数写进日志
            request.path,
            response.status_code,
            duration_ms,
        )
        return response
