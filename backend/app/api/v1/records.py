# -*- coding: utf-8 -*-
"""健康记录 API（本批实现 **R-01 ~ R-08**）。

依据：《S1-B 第二批 API 接口设计文档》§七

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| R-01 | ``POST /api/v1/records`` | ✅ | F-015~F-022 / F-023 / F-024 |
| R-02 | ``GET /api/v1/records`` | ✅ | F-025 / F-036 |
| R-03 | ``GET /api/v1/records/{id}`` | ✅ | F-026 |
| R-04 | ``PATCH /api/v1/records/{id}`` | ✅ | F-027 |
| R-05 | ``DELETE /api/v1/records/{id}`` | ✅ | F-028 |
| R-06 | ``POST /api/v1/records/batch-delete`` | ✅ | F-072 |
| R-07 | ``GET /api/v1/records/count`` | ✅ | F-070 / F-072 |
| R-08 | ``GET /api/v1/records/options`` | ✅ | F-015~F-022 / F-011 |

> 本模块**只承载协议与边界**；业务判定在 ``app/services/record_service.py``。
> ``user_id`` **只来自 Access Token**；客户端提交 ``user_id`` → 全局守卫 ``400``。
> 路径参数一律 ``<int:record_id>``，静态路径（``count`` / ``options`` / ``batch-delete``）
> 与动态路径不冲突。
"""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, request

from app.core import idempotency
from app.core.auth import current_user, current_user_id, require_auth
from app.core.db import get_db
from app.core.errors import ERROR_MESSAGE, ApiError, ErrorCode
from app.core.response import api_response, ok
from app.schemas.base import load_json_b3
from app.schemas.record import BatchDeleteSchema, RecordCreateSchema, RecordPatchSchema
from app.services import record_service

bp = Blueprint("records", __name__)


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


@bp.post("/records")
@require_auth
def create_record():
    """R-01 新增健康记录（支持 ``Idempotency-Key``）。"""
    user_id = current_user_id()
    body = _raw_body()
    key = idempotency.normalize_key(request.headers.get(idempotency.IDEMPOTENCY_HEADER))

    replay = record_service.lookup_idempotent(user_id, key, body)
    if replay is not None:
        return api_response(
            data=replay["data"], message=replay["message"],
            code=replay["code"], http_status=replay["status"],
        )

    payload = load_json_b3(RecordCreateSchema())
    acknowledge = bool(payload.get("acknowledge_warnings"))
    kind, data = record_service.create_record(get_db(), user_id, payload, acknowledge)
    if kind == "soft_warning":
        return _soft_warning(data)

    record_service.remember_idempotent(user_id, key, body, 201, "OK", "已保存", data)
    return api_response(data=data, message="已保存", http_status=201)


@bp.get("/records")
@require_auth
def list_records():
    """R-02 记录列表（游标分页 + 半开区间筛选；**不返回 total**）。"""
    return ok(data=record_service.list_records(get_db(), current_user_id(), request.args),
              message="成功")


@bp.get("/records/count")
@require_auth
def count_records():
    """R-07 记录条数统计。"""
    return ok(data=record_service.count_records(get_db(), current_user_id(), request.args),
              message="成功")


@bp.get("/records/options")
@require_auth
def record_options():
    """R-08 录入选项（静态枚举字典，**不访问数据库**）。"""
    return ok(data=record_service.list_options(), message="成功")


@bp.post("/records/batch-delete")
@require_auth
def batch_delete_records():
    """R-06 批量删除（密码验证 + 条数一致性 + 大数量二次确认）。"""
    user_id = current_user_id()
    body = _raw_body()
    key = idempotency.normalize_key(request.headers.get(idempotency.IDEMPOTENCY_HEADER))

    replay = record_service.lookup_idempotent(user_id, key, body)
    if replay is not None:
        return api_response(
            data=replay["data"], message=replay["message"],
            code=replay["code"], http_status=replay["status"],
        )

    payload = load_json_b3(BatchDeleteSchema())
    data = record_service.batch_delete(get_db(), current_user(), payload)
    message = f"已删除 {data['deleted_count']} 条"
    record_service.remember_idempotent(user_id, key, body, 200, "OK", message, data)
    return ok(data=data, message=message)


@bp.get("/records/<int:record_id>")
@require_auth
def get_record(record_id: int):
    """R-03 记录详情（``id + user_id`` 双条件；跨用户 / 不存在 / 已软删 → 404）。"""
    return ok(data=record_service.get_record(get_db(), current_user_id(), record_id),
              message="成功")


@bp.patch("/records/<int:record_id>")
@require_auth
def patch_record(record_id: int):
    """R-04 修改记录（``metric_type`` 不允许修改；标签整体替换）。"""
    body = _raw_body()
    payload = load_json_b3(RecordPatchSchema())
    acknowledge = bool(payload.get("acknowledge_warnings"))
    kind, data = record_service.patch_record(
        get_db(), current_user_id(), record_id, payload, acknowledge
    )
    if kind == "soft_warning":
        return _soft_warning(data)
    return ok(data=data, message="已保存")


@bp.delete("/records/<int:record_id>")
@require_auth
def delete_record(record_id: int):
    """R-05 单条删除（软删 + 标签同步软删）。"""
    data = record_service.delete_record(get_db(), current_user_id(), record_id)
    return ok(data=data, message=f"已删除 {data['deleted_count']} 条")


__all__ = ["bp"]
