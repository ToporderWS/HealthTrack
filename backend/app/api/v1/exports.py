# -*- coding: utf-8 -*-
"""数据导出 API（本批实现 **E-01 ~ E-04**）。

依据：《S1-B 第二批 API 接口设计文档》§十（模块 E）· 《S1-A 安全规则冻结清单》§4 / §8

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| E-01 | ``POST /api/v1/exports`` | ✅ | F-071 |
| E-02 | ``GET /api/v1/exports/{id}`` | ✅ | F-071 |
| E-03 | ``GET /api/v1/exports/{id}/download?file_token=...`` | ✅ 双重校验 | F-071 |
| E-04 | ``GET /api/v1/exports`` | ✅ | F-071 |

> 本模块**只承载协议与边界**；业务判定在 ``app/services/export_service.py``。
> ``user_id`` **只来自 Access Token**；客户端以任何方式提交 ``user_id`` → 全局守卫 ``400``。
> E-03 返回**文件流**（非 JSON 包装），故**不用** ``api_response``，但响应头仍带 ``X-Request-Id``。
> 响应**永不返回** ``file_path``；导出内容不含软删数据 / ``user_id`` / 内部主键 ``id``。
"""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, Response, current_app, request, send_file

from app.core import idempotency
from app.core.auth import current_session, current_user, current_user_id, require_auth
from app.core.db import get_db
from app.core.errors import ApiError, ErrorCode
from app.core.request_id import get_request_id
from app.core.response import api_response
from app.services import export_service

bp = Blueprint("exports", __name__)

#: E-01 成功文案（冻结）
CREATE_MESSAGE = "导出任务已创建"
#: E-01 成功 HTTP 状态码（冻结）
CREATE_STATUS = 202


def _json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)
    return body


@bp.post("/exports")
@require_auth
def create_export():
    """E-01 创建导出任务（**同步生成**，成功即 ``ready``；二次验密不可豁免）。"""
    user_id = current_user_id()
    body = _json_body()

    key = idempotency.normalize_key(request.headers.get(idempotency.IDEMPOTENCY_HEADER))
    replay = idempotency.lookup(user_id, key, body)
    if replay is not None:
        return api_response(
            data=replay["data"], message=replay["message"],
            code=replay["code"], http_status=replay["status"],
        )

    data = export_service.create_export(
        get_db(), current_app.config,
        user_id=user_id, session=current_session(), account=current_user(), payload=body,
    )
    idempotency.remember(user_id, key, body, CREATE_STATUS, "OK", CREATE_MESSAGE, data)
    return api_response(data=data, message=CREATE_MESSAGE, code="OK", http_status=CREATE_STATUS)


@bp.get("/exports")
@require_auth
def list_exports():
    """E-04 导出任务列表（游标分页，``created_at DESC``）。"""
    return api_response(
        data=export_service.list_exports(get_db(), current_user_id(), request.args),
        message="成功", code="OK", http_status=200,
    )


@bp.get("/exports/<int:export_id>")
@require_auth
def get_export(export_id: int):
    """E-02 导出任务查询（非本人 → 404，不暴露存在性）。"""
    return api_response(
        data=export_service.get_export(get_db(), current_user_id(), export_id),
        message="成功", code="OK", http_status=200,
    )


@bp.get("/exports/<int:export_id>/download")
@require_auth
def download_export(export_id: int):
    """E-03 下载导出文件（``id + user_id + file_token`` 三条件；200 文件流）。"""
    job = export_service.resolve_download(
        get_db(), current_user_id(), export_id, request.args.get("file_token")
    )
    path = export_service.safe_download_path(job.file_path)
    mime = export_service.content_type_of(job)
    filename = export_service.download_filename(job)

    response: Response = send_file(path, mimetype=mime, as_attachment=True,
                                   download_name=filename, conditional=False)
    # 冻结口径：Content-Type 带 charset；Content-Disposition 固定形态（服务端生成文件名）；
    # 响应头必须与统一契约一致地携带 X-Request-Id。**不得**出现服务器真实路径。
    response.headers["Content-Type"] = f"{mime}; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["X-Request-Id"] = get_request_id()
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ["bp"]
