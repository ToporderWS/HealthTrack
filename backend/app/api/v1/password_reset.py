# -*- coding: utf-8 -*-
"""找回密码 API（**B2**：PR-01 / PR-02 / PR-03）。

依据：《忘记密码自助找回 · 开工前只读审计与方案报告》§6.2 / §6.3；
需求方 B2 授权 §五 / §六 / §七。

| 编号 | Method / Path | 鉴权 | 说明 |
|---|---|---|---|
| PR-01 | ``POST /api/v1/auth/password-reset/request`` | **免登录** | 发起找回（**恒等响应**，防账号枚举） |
| PR-02 | ``POST /api/v1/auth/password-reset/verify`` | **免登录** | 校验验证码 → 签发一次性 ``reset_token`` |
| PR-03 | ``POST /api/v1/auth/password-reset/confirm`` | **免登录** | 用 ``reset_token`` 设置新密码 |

设计边界（**本模块只承载协议**，业务判定在 ``services/password_reset_service.py``）
---------------------------------------------------------------------------------
- 三条路由**一律不加** ``@require_auth``：找回是**未登录**场景的入口；
- PR-03 的 ``reset_token`` 走**请求体**，**不是** ``Authorization: Bearer``；
- ``reset_token`` **不是** Access / Refresh Token，**不建立任何登录态**；
- 全局身份守卫仍然生效：请求体/query 中出现 ``user_id`` → ``400 INVALID_PARAM``；
- 响应统一走 ``api_response`` / ``ok``（自动携带 ``X-Request-Id``）。
"""
from __future__ import annotations

from flask import Blueprint, current_app

from app.core.db import get_db
from app.core.response import ok
from app.schemas.common import load_json
from app.schemas.password_reset import (
    PasswordResetConfirmSchema,
    PasswordResetRequestSchema,
    PasswordResetVerifySchema,
)
from app.services import password_reset_service

bp = Blueprint("password_reset", __name__)


@bp.post("/auth/password-reset/request")
def request_password_reset():
    """PR-01 发起找回。

    **四态恒等**：账号存在且已绑定已验证邮箱 / 不存在 / 未绑定邮箱 / 冷却期内
    ⇒ 同一 ``code`` ＋ 同一 ``message`` ＋ 同一 HTTP 200 ＋ 同一 ``data: null``。
    """
    payload = load_json(PasswordResetRequestSchema())
    outcome = password_reset_service.request_password_reset(
        get_db(),
        current_app.config,
        username_raw=payload["username"],
    )
    return ok(data=outcome["data"], message=outcome["message"])


@bp.post("/auth/password-reset/verify")
def verify_password_reset_code():
    """PR-02 校验验证码（成功返回一次性 ``reset_token``）。"""
    payload = load_json(PasswordResetVerifySchema())
    outcome = password_reset_service.verify_password_reset_code(
        get_db(),
        current_app.config,
        username_raw=payload["username"],
        code_raw=payload["code"],
    )
    return ok(data=outcome["data"], message=outcome["message"])


@bp.post("/auth/password-reset/confirm")
def confirm_password_reset():
    """PR-03 设置新密码（成功后该账号全部会话失效）。"""
    payload = load_json(PasswordResetConfirmSchema())
    outcome = password_reset_service.confirm_password_reset(
        get_db(),
        current_app.config,
        reset_token_raw=payload["reset_token"],
        new_password_raw=payload["new_password"],
        confirm_password_raw=payload["confirm_password"],
    )
    return ok(data=outcome["data"], message=outcome["message"])


__all__ = ["bp"]
