# -*- coding: utf-8 -*-
"""邮箱绑定 API（**B3 第一批**：PR-04 / PR-05）。

依据：需求方 B3 授权（2026-09-24）§二（实施范围）／§四（事务语义）／§五（安全要求）。

| 编号 | Method / Path | 鉴权 | 说明 |
|---|---|---|---|
| PR-04 | ``POST /api/v1/auth/email/bind-request`` | ✅ **需登录** | 复验当前密码 → 发绑定验证码（**恒等响应**） |
| PR-05 | ``POST /api/v1/auth/email/bind-confirm`` | ✅ **需登录** | 复验当前密码 → 校验码 → 同事务写 ``email`` ＋ ``email_verified_at`` |

设计边界（**本模块只承载协议**，业务判定在 ``services/email_bind_service.py``）
---------------------------------------------------------------------------
- 两条路由**一律加** ``@require_auth``：邮箱绑定是**已登录**场景的敏感操作；
- 身份**只**来自 ``current_user``（``Access Token`` 解析结果）；**不接受** body 传 ``user_id``
  —— 全局身份守卫（``core/auth.py::register_identity_guard``）会把它拦成 ``400 INVALID_PARAM``；
- 响应统一走 ``api_response`` / ``ok``（自动携带 ``X-Request-Id``）；
- **不新增页面**、**不碰 frontend**（A2 前端入口归 B4）。
"""
from __future__ import annotations

from flask import Blueprint, current_app

from app.core.auth import current_user, require_auth
from app.core.db import get_db
from app.core.response import ok
from app.schemas.common import load_json
from app.schemas.email_bind import EmailBindConfirmSchema, EmailBindRequestSchema
from app.services import email_bind_service

bp = Blueprint("email_bind", __name__)


@bp.post("/auth/email/bind-request")
@require_auth
def request_email_bind():
    """PR-04 发起邮箱绑定（**恒等响应**，不泄露目标邮箱是否已被占用）。"""
    payload = load_json(EmailBindRequestSchema())
    outcome = email_bind_service.request_email_bind(
        get_db(),
        current_app.config,
        account=current_user(),
        email_raw=payload["email"],
        current_password_raw=payload["current_password"],
    )
    return ok(data=outcome["data"], message=outcome["message"])


@bp.post("/auth/email/bind-confirm")
@require_auth
def confirm_email_bind():
    """PR-05 校验验证码并落库（成功后旧邮箱立即失效；**不撤销会话**）。"""
    payload = load_json(EmailBindConfirmSchema())
    outcome = email_bind_service.confirm_email_bind(
        get_db(),
        current_app.config,
        account=current_user(),
        email_raw=payload["email"],
        code_raw=payload["code"],
        current_password_raw=payload["current_password"],
    )
    return ok(data=outcome["data"], message=outcome["message"])


__all__ = ["bp"]
