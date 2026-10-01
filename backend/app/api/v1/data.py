# -*- coding: utf-8 -*-
"""数据管理 API（本批实现 **D-01 / D-02**）。

依据：《S1-B 第二批 API 接口设计文档》§十一（模块 D）· 《S1-B 数据库设计文档》§12.5

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| D-01 | ``GET /api/v1/me/data/summary`` | ✅ | F-070 |
| D-02 | ``POST /api/v1/me/data/clear`` | ✅ | F-073 |

> 本模块**只承载协议与边界**；业务判定在 ``app/services/data_service.py``。
> ``user_id`` **只来自 Access Token**；客户端以任何方式提交 ``user_id`` → 全局守卫 ``400``。
> D-02 为破坏性写接口：**单事务 + 异常整体回滚**；范围扩展参数（``include_profile_row`` /
> ``delete_account`` 等）**契约未定义，一律无效果**（不实现、不识别）。
> 响应结构走统一 envelope（自动携带 ``X-Request-Id``）。
"""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, request

from app.core.auth import current_user, current_user_id, require_auth
from app.core.db import get_db
from app.core.errors import ApiError, ErrorCode
from app.core.response import api_response
from app.services import data_service

bp = Blueprint("data", __name__)

#: 成功文案（成功响应恒为统一 envelope；``message`` 默认「成功」）
OK_MESSAGE = "成功"
OK_STATUS = 200


def _json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)
    return body


@bp.get("/me/data/summary")
@require_auth
def data_summary():
    """D-01 数据总览（**只返回条数与时间范围**；空数据 → ``total_records=0`` / ``by_metric=[]``）。"""
    return api_response(
        data=data_service.summary(get_db(), current_user_id()),
        message=OK_MESSAGE, code="OK", http_status=OK_STATUS,
    )


@bp.post("/me/data/clear")
@require_auth
def clear_data():
    """D-02 清空全部数据（三重确认 + 单事务；**保留账号**）。"""
    data = data_service.clear_all_data(
        get_db(),
        user_id=current_user_id(),
        account=current_user(),
        payload=_json_body(),
    )
    return api_response(
        data=data,
        message=data_service.clear_message(int(data["deleted_records"])),
        code="OK", http_status=OK_STATUS,
    )


__all__ = ["bp"]
