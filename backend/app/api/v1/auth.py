# -*- coding: utf-8 -*-
"""认证与会话 API（模块 A，本批实现 **A-01 ~ A-05**）。

依据：《S1-B 第二批 API 接口设计文档》§五。

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| A-01 | ``POST /api/v1/auth/register`` | 免登录 | F-001 / F-008 / F-076 |
| A-02 | ``POST /api/v1/auth/login`` | 免登录 | F-002 / F-077 |
| A-03 | ``POST /api/v1/auth/refresh`` | 免登录（需 refresh_token） | F-077 |
| A-04 | ``POST /api/v1/auth/logout`` | ✅ | F-003 / F-077 |
| A-05 | ``PUT  /api/v1/auth/password`` | ✅ | F-004 / F-076 / F-077 |

> **A-07 注销账号（``DELETE /api/v1/users/me``）不在本批范围**（R-13 全量物理删除，另批实施）。
"""
from __future__ import annotations

from flask import Blueprint, current_app

from app.core.auth import current_session, current_user, require_auth
from app.core.db import get_db
from app.core.response import api_response, ok
from app.schemas.auth import (
    ChangePasswordSchema,
    LoginSchema,
    RefreshSchema,
    RegisterSchema,
)
from app.schemas.common import load_json
from app.services import auth_service

bp = Blueprint("auth", __name__)


@bp.post("/auth/register")
def register():
    """A-01 注册（成功 **201**）。"""
    payload = load_json(RegisterSchema())
    data = auth_service.register_user(
        get_db(),
        current_app.config,
        username_raw=payload["username"],
        password_raw=payload["password"],
        agreement_version_raw=payload["agreement_version"],
        agreement_accepted=payload["agreement_accepted"],
        auto_login=bool(payload.get("auto_login", True)),
    )
    return api_response(data=data, message="注册成功", http_status=201)


@bp.post("/auth/login")
def login():
    """A-02 登录（含失败锁定；成功返回 200）。"""
    payload = load_json(LoginSchema())
    data = auth_service.login_user(
        get_db(),
        current_app.config,
        username_raw=payload["username"],
        password_raw=payload["password"],
    )
    return ok(data=data, message="登录成功")


@bp.post("/auth/refresh")
def refresh():
    """A-03 刷新 Token（单次使用 + 轮换 + 重放防护）。"""
    payload = load_json(RefreshSchema())
    tokens = auth_service.refresh_tokens(
        get_db(), current_app.config, refresh_token_raw=payload["refresh_token"]
    )
    return ok(data=tokens, message="成功")


@bp.post("/auth/logout")
@require_auth
def logout():
    """A-04 退出登录（**仅失效当前会话**，不动任何业务数据）。

    注：I-01「登出后取消已注册的系统本地通知」属**前端**职责，
    本批不含前端 UI，已列入后续前端批次待测项。
    """
    auth_service.logout_session(get_db(), current_session())
    return ok(data=None, message="已退出登录")


@bp.put("/auth/password")
@require_auth
def change_password():
    """A-05 修改密码（成功后**该账号全部旧 Token 立即失效**）。"""
    payload = load_json(ChangePasswordSchema())
    data = auth_service.change_password(
        get_db(),
        current_app.config,
        account=current_user(),
        session=current_session(),
        old_password_raw=payload["old_password"],
        new_password_raw=payload["new_password"],
        confirm_password_raw=payload["confirm_password"],
    )
    return ok(data=data, message="密码已修改，请重新登录")


__all__ = ["bp"]
