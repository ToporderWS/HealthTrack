# -*- coding: utf-8 -*-
"""账号 API（本批实现 **A-07 注销账号**）。

依据：《S1-B 第二批 API 接口设计文档》§五 A-07（679~727）· §十五 15.4（2055~2076）

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| A-07 | ``DELETE /api/v1/users/me`` | ✅ | F-005、F-077、F-078 |

> 本模块**只承载协议与边界**；业务判定在 ``app/services/account_service.py``。
> ``user_id`` **只来自 Access Token**；客户端以任何方式提交 ``user_id`` → 全局守卫 ``400``。
> **不接受**任何范围扩展参数（``target_user_id`` / ``grace_period`` / ``defer`` / ``schedule`` /
> ``force`` 等契约未定义项一律无效果）。
> A-07 与 A-06 是**同一路径不同方法**（``GET`` 在 ``users.py``，``DELETE`` 在本模块）——
> 采用**独立 account 蓝图**，避免修改已封板的 ``users.py``。
> 响应结构走统一 envelope（自动携带 ``X-Request-Id``）。
"""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, request

from app.core.auth import current_user, current_user_id, require_auth
from app.core.db import get_db
from app.core.errors import ApiError, ErrorCode
from app.core.response import api_response
from app.services import account_service

bp = Blueprint("account", __name__)

#: A-07 成功状态码（冻结）
OK_STATUS = 200


def _json_body() -> Dict[str, Any]:
    """A-07 请求体（``password`` / ``confirm_text`` / 可选 ``client_time``）。

    非 JSON 对象 → ``400 INVALID_PARAM``（与全局参数口径一致）。
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)
    return body


@bp.delete("/users/me")
@require_auth
def close_current_account():
    """A-07 注销账号（三重确认 + 单事务物理删除；事务外处置导出文件）。"""
    data = account_service.close_account(
        get_db(),
        user_id=current_user_id(),
        account=current_user(),
        payload=_json_body(),
    )
    return api_response(
        data=data,
        message=account_service.CLOSED_MESSAGE,
        code="OK",
        http_status=OK_STATUS,
    )


__all__ = ["bp"]
