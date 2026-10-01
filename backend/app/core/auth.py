# -*- coding: utf-8 -*-
"""认证中间件与身份上下文。

依据：
- 《S1-D 技术方案最终冻结》§6.1「Session 权威」：``user_session`` 为**唯一权威**，
  Access Token 校验**必须同时校验 `jti` 未被失效**（``revoked_at IS NULL`` 且未过期）
- 《S1-D》§6.3「``user_id`` 来源」：**只能由服务端从 Access Token 解析**；
  **请求中出现 ``user_id`` → 400**
- 《S1-B 第二批 API 接口设计文档》§五：A-04 / A-05 / A-06 需登录

设计要点：
1. ``require_auth`` 装饰器完成「Bearer 解析 → JWT 校验 → Session 有效性校验 → 用户装载」
   四步；任何一步失败统一 ``401 UNAUTHENTICATED``（不区分原因，避免信息泄露）。
2. 身份只挂在 ``flask.g`` 上，视图函数**不得**从请求体 / query / 路径取 ``user_id``。
3. :func:`register_identity_guard` 注册全局 ``before_request``：请求中出现 ``user_id``
   一律 ``400 INVALID_PARAM``（含请求体与 query）。
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional, Tuple

from flask import Flask, current_app, g, request
from sqlalchemy import select

from app.core.db import get_db
from app.core.errors import ApiError, ErrorCode
from app.core.security import decode_access_token, now_local
from app.models.user_account import UserAccount
from app.models.user_session import UserSession

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "


def _bearer_token() -> str:
    """从 ``Authorization: Bearer <token>`` 取令牌。"""
    raw = request.headers.get(AUTHORIZATION_HEADER) or ""
    if not raw.startswith(BEARER_PREFIX):
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    token = raw[len(BEARER_PREFIX):].strip()
    if not token:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    return token


def load_identity() -> Tuple[UserAccount, UserSession]:
    """解析并校验当前请求身份（失败统一 401）。"""
    cfg = current_app.config
    payload = decode_access_token(_bearer_token(), cfg.get("SECRET_KEY") or "")

    jti = str(payload.get("jti"))
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise ApiError(ErrorCode.UNAUTHENTICATED)

    db = get_db()
    # 索引 idx_session_access(access_token_id) —— 访问令牌校验入口
    session = db.execute(
        select(UserSession).where(
            UserSession.access_token_id == jti,
            UserSession.user_id == user_id,
        )
    ).scalars().first()

    # Session 是唯一权威：不存在 / 已失效 → 401
    if session is None or session.revoked_at is not None:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    if session.access_expires_at <= now_local():
        raise ApiError(ErrorCode.UNAUTHENTICATED)

    user = db.get(UserAccount, user_id)
    if user is None:
        # 账号已不存在（如并发注销）→ 登录态自然失效
        raise ApiError(ErrorCode.UNAUTHENTICATED)

    return user, session


def require_auth(view: Callable) -> Callable:
    """需登录接口装饰器：成功后 ``g.current_user`` / ``g.current_session`` 可用。"""

    @wraps(view)
    def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        user, session = load_identity()
        g.current_user = user
        g.current_session = session
        return view(*args, **kwargs)

    return wrapper


def current_user() -> Optional[UserAccount]:
    return g.get("current_user")


def current_session() -> Optional[UserSession]:
    return g.get("current_session")


def current_user_id() -> int:
    """当前用户主键（**唯一合法来源**：Access Token 解析结果）。"""
    user = current_user()
    if user is None:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    return int(user.id)


def register_identity_guard(app: Flask) -> None:
    """全局守卫：请求中出现 ``user_id`` → ``400 INVALID_PARAM``。

    冻结口径（S1-D §6.3）：``user_id`` **只能由服务端从 Token 解析**，
    客户端提交 ``user_id`` 属非法参数（无论请求体或 URL query）。
    """

    @app.before_request
    def _reject_client_user_id():  # noqa: ANN202
        if "user_id" in request.args:
            raise ApiError(ErrorCode.INVALID_PARAM)
        if request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, dict) and "user_id" in body:
                raise ApiError(ErrorCode.INVALID_PARAM)
        return None


__all__ = [
    "require_auth",
    "load_identity",
    "current_user",
    "current_session",
    "current_user_id",
    "register_identity_guard",
]
