# -*- coding: utf-8 -*-
"""档案 API（本批实现 **P-01 / P-02**）。

依据：《S1-B 第二批 API 接口设计文档》§六

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| P-01 | ``GET /api/v1/profile`` | ✅ | F-060 / F-061 / F-062 |
| P-02 | ``PUT /api/v1/profile`` | ✅ | F-060 / F-061 / F-062 / F-023 |

口径：
- ``user_id`` **只来自 Access Token**（客户端提交 ``user_id`` → 全局守卫 ``400``）；
- 未初始化档案 → 返回**全 null 的 profile 对象**（**不是 404**）；
- 软提示 → **HTTP 200 + ``SOFT_WARNING``**，**本次不写入**（需 ``acknowledge_warnings=true`` 重发）；
- 文本字段**原样存储与回显，不做任何解读**。
"""
from __future__ import annotations

from flask import Blueprint, request

from app.core.auth import current_user, require_auth
from app.core.db import get_db
from app.core.errors import ERROR_MESSAGE, ErrorCode
from app.core.response import api_response, ok
from app.core.warnings import soft_warning_payload
from app.schemas.base import load_json_b3
from app.schemas.profile import ProfileUpdateSchema
from app.services import profile_service

bp = Blueprint("profile", __name__)


@bp.get("/profile")
@require_auth
def get_profile():
    """P-01 获取当前用户档案（含 ``age`` / ``bmi`` 派生值 + 目标体重取数指引）。"""
    return ok(data=profile_service.get_profile(get_db(), current_user()), message="成功")


@bp.put("/profile")
@require_auth
def put_profile():
    """P-02 整体替换档案（UPSERT；支持软提示确认后写入）。"""
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        from app.core.errors import ApiError

        raise ApiError(ErrorCode.INVALID_PARAM)

    # D-1 保护：本接口不接受 target_weight（防双数据源）
    profile_service.ensure_no_target_weight(raw)

    payload = load_json_b3(ProfileUpdateSchema())
    acknowledge = bool(payload.get("acknowledge_warnings"))
    profile, warnings = profile_service.update_profile(
        get_db(), current_user(), payload, acknowledge
    )

    if profile is None:
        # 软提示：本次不写入
        return api_response(
            code=ErrorCode.SOFT_WARNING,
            message=ERROR_MESSAGE[ErrorCode.SOFT_WARNING],
            data=soft_warning_payload(warnings),
            http_status=200,
        )
    return ok(
        data={"profile": profile_service.profile_payload(profile), "warnings": list(warnings)},
        message="已保存",
    )


__all__ = ["bp"]
