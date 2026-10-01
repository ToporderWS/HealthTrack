# -*- coding: utf-8 -*-
"""用户信息 API（本批实现 **A-06**）。

依据：《S1-B 第二批 API 接口设计文档》§五 A-06。

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| A-06 | ``GET /api/v1/users/me`` | ✅ | F-064 / F-078 |

> **A-07 注销账号（``DELETE /api/v1/users/me``）不在本批范围**。
> 本模块**只读** ``user_account`` 的 ``username`` / ``created_at``；
> ``user_id`` **只来自 Access Token**（不接受任何请求参数）。
"""
from __future__ import annotations

from flask import Blueprint

from app.core.auth import current_user, require_auth
from app.core.db import get_db
from app.core.response import ok
from app.services import auth_service

bp = Blueprint("users", __name__)


@bp.get("/users/me")
@require_auth
def get_me():
    """A-06 获取当前登录用户信息。"""
    return ok(data=auth_service.build_current_user(get_db(), current_user()), message="成功")


__all__ = ["bp"]
