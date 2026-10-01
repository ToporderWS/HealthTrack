# -*- coding: utf-8 -*-
"""头像 API（S4-2B 实现 **AV-01 / AV-02 / AV-03**）。

依据：《康迹 HealthTrack · S4-2A 头像上传技术方案与开工前审计报告》（需求方 2026-09-22 审核通过）

| API | Method / Path | 鉴权 | 说明 |
|---|---|---|---|
| AV-01 | ``POST /api/v1/profile/avatar`` | ✅ | ``multipart/form-data``，字段 ``file``；上传或更换 |
| AV-02 | ``DELETE /api/v1/profile/avatar`` | ✅ | **幂等**删除 / 恢复默认头像 |
| AV-03 | ``GET /api/v1/profile/avatar`` | ✅ | 返回**本人**头像文件流 |

口径（冻结）：

- **三个端点全部 `@require_auth`**；``user_id`` **只来自 Access Token**
  ⇒ 不可能读取 / 修改他人头像（**无任何路径参数、无任何资源标识参数**）。
- AV-03 的 URL **恒定为 ``/profile/avatar``，不含 ``user_id`` / ``avatar_key`` 或任何标识**
  ⇒ 既不能枚举他人，也不产生可转发 / 可缓存的公开资源地址。
- 响应与响应头**永不出现**：``avatar_key``、服务器绝对路径、原始文件名、``user_id``。
- 上传体**不走 JSON 路由**（``multipart/form-data``）；``file`` 字段名冻结为 ``file``。
- **本批仅此 3 个端点**，不新增任何其它路由。
- 业务判定全部在 ``app/services/avatar_service.py``；本模块**只承载协议与边界**。
"""
from __future__ import annotations

from flask import Blueprint, Response, request

from app.core.auth import current_user_id, require_auth
from app.core.db import get_db
from app.core.response import api_response
from app.services import avatar_service

bp = Blueprint("avatar", __name__)


@bp.post("/profile/avatar")
@require_auth
def upload_avatar():
    """AV-01 上传 / 更换头像（``multipart/form-data``，字段 ``file``）。"""
    data = avatar_service.save_avatar(
        get_db(),
        user_id=current_user_id(),
        files=request.files,
        form=request.form,
    )
    return api_response(
        data=data, message=avatar_service.UPDATED_MESSAGE, code="OK", http_status=200
    )


@bp.delete("/profile/avatar")
@require_auth
def delete_avatar():
    """AV-02 删除头像 / 恢复默认（**幂等**：重复调用同样返回成功）。"""
    data = avatar_service.clear_avatar(get_db(), user_id=current_user_id())
    return api_response(
        data=data, message=avatar_service.CLEARED_MESSAGE, code="OK", http_status=200
    )


@bp.get("/profile/avatar")
@require_auth
def get_avatar():
    """AV-03 读取本人头像（**文件流**，非 JSON 包装；响应头按冻结清单设置）。"""
    response: Response = avatar_service.load_avatar(get_db(), user_id=current_user_id())
    return response


__all__ = ["bp"]
