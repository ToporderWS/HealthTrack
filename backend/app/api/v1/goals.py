# -*- coding: utf-8 -*-
"""健康目标 API（本批实现 **G-01 ~ G-07**）。

依据：《S1-B 第二批 API 接口设计文档》§八

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| G-01 | ``GET /api/v1/goals`` | ✅ | F-041~F-044 / F-046 |
| G-02 | ``POST /api/v1/goals`` | ✅ | F-041~F-045 |
| G-03 | ``PATCH /api/v1/goals/{id}`` | ✅ | F-045 |
| G-04 | ``POST /api/v1/goals/{id}/pause`` | ✅ | F-045 |
| G-05 | ``POST /api/v1/goals/{id}/resume`` | ✅ | F-045 |
| G-06 | ``DELETE /api/v1/goals/{id}`` | ✅ | F-045 |
| G-07 | ``GET /api/v1/goals/progress`` | ✅ | F-046 / F-013 |

> 本模块**只承载协议与边界**；业务判定在 ``app/services/goal_service.py`` 与
> ``app/services/goal_progress.py``。
> ``user_id`` **只来自 Access Token**；客户端提交 ``user_id`` → 全局守卫 ``400``。
> 路径参数一律 ``<int:goal_id>``；静态路径 ``progress`` 与动态路径不冲突
> （``<int:>`` 不匹配 ``progress``，与 R 模块 ``count``/``options`` 同模式）。
> **本批不接入 ``Idempotency-Key``**（G 模块冻结设计未要求；G-02 按业务语义非幂等）。
"""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, request

from app.core.auth import current_user_id, require_auth
from app.core.db import get_db
from app.core.errors import ERROR_MESSAGE, ApiError, ErrorCode
from app.core.response import api_response, ok
from app.schemas.base import load_json_b3
from app.schemas.goal import GoalCreateSchema, GoalPatchSchema
from app.services import goal_progress, goal_service

bp = Blueprint("goals", __name__)


def _raw_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)
    return body


def _soft_warning(data: Dict[str, Any]):
    return api_response(
        code=ErrorCode.SOFT_WARNING,
        message=ERROR_MESSAGE[ErrorCode.SOFT_WARNING],
        data=data,
        http_status=200,
    )


@bp.get("/goals")
@require_auth
def list_goals():
    """G-01 目标列表（**不分页**；``include_history`` 为只读展示）。"""
    return ok(data=goal_service.list_goals(get_db(), current_user_id(), request.args),
              message="成功")


@bp.get("/goals/progress")
@require_auth
def goals_progress():
    """G-07 目标完成度（四类算法实时计算；**派生值不落库**）。"""
    return ok(data=goal_progress.list_progress(get_db(), current_user_id(), request.args),
              message="成功")


@bp.post("/goals")
@require_auth
def create_goal():
    """G-02 创建目标（``period_type`` / ``unit`` 服务端强制；同类在用目标 → 409）。"""
    payload = load_json_b3(GoalCreateSchema())
    acknowledge = bool(payload.get("acknowledge_warnings"))
    kind, data = goal_service.create_goal(get_db(), current_user_id(), payload, acknowledge)
    if kind == "soft_warning":
        return _soft_warning(data)
    return api_response(data=data, message="目标已创建", http_status=201)


@bp.patch("/goals/<int:goal_id>")
@require_auth
def patch_goal(goal_id: int):
    """G-03 修改目标（``goal_type`` / ``start_weight_kg`` 不允许修改）。"""
    payload = load_json_b3(GoalPatchSchema())
    acknowledge = bool(payload.get("acknowledge_warnings"))
    kind, data = goal_service.patch_goal(
        get_db(), current_user_id(), goal_id, payload, acknowledge
    )
    if kind == "soft_warning":
        return _soft_warning(data)
    return ok(data=data, message="已保存")


@bp.post("/goals/<int:goal_id>/pause")
@require_auth
def pause_goal(goal_id: int):
    """G-04 暂停目标（已暂停再调 → ``changed: false``）。"""
    data = goal_service.pause_goal(get_db(), current_user_id(), goal_id)
    return ok(data=data, message="目标已暂停")


@bp.post("/goals/<int:goal_id>/resume")
@require_auth
def resume_goal(goal_id: int):
    """G-05 恢复目标（同类型已有另一条在用目标 → 409）。"""
    data = goal_service.resume_goal(get_db(), current_user_id(), goal_id)
    return ok(data=data, message="目标已恢复")


@bp.delete("/goals/<int:goal_id>")
@require_auth
def delete_goal(goal_id: int):
    """G-06 删除目标（**软删三件事齐全**；重复删除 → 404）。"""
    data = goal_service.delete_goal(get_db(), current_user_id(), goal_id)
    return ok(data=data, message="已删除")


__all__ = ["bp"]
