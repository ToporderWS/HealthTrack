# -*- coding: utf-8 -*-
"""错误码体系与统一异常处理。

依据：《S1-B 第二批 API 接口设计文档》§3.6 错误码体系（**共 18 个**）

变更登记（``CR-F006-001`` · B3 授权 §Q-B3-03，2026-09-24）：
**追加 1 个**业务错误码 ``EMAIL_TAKEN``（HTTP 409）⇒ 当前共 **19** 个。
``add-only``：既有的 18 个错误码**语义 / 编号规则 / HTTP 状态一律未改**。

约定：
- **错误码只增不改**：新增属兼容性变更；修改既有语义属破坏性变更，须走变更流程。
- ``500 INTERNAL_ERROR`` **不返回任何内部细节**。
- 本模块只建立**基础异常处理骨架**，不实现任何业务错误的判定逻辑（属后续批次）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flask import Flask
from werkzeug.exceptions import HTTPException

from app.core.response import api_response

logger = logging.getLogger(__name__)


class ErrorCode:
    """S1-B 冻结的 18 个错误码（+ 成功码 OK）；B3 追加 ``EMAIL_TAKEN`` ⇒ 19 个。"""

    # 400
    INVALID_PARAM = "INVALID_PARAM"
    # 401
    UNAUTHENTICATED = "UNAUTHENTICATED"
    CREDENTIALS_INVALID = "CREDENTIALS_INVALID"
    TOKEN_REUSED = "TOKEN_REUSED"
    # 404
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    # 409
    USERNAME_TAKEN = "USERNAME_TAKEN"
    GOAL_TYPE_EXISTS = "GOAL_TYPE_EXISTS"
    EXPORT_IN_PROGRESS = "EXPORT_IN_PROGRESS"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    COUNT_MISMATCH = "COUNT_MISMATCH"
    #: **B3 追加**（CR-F006-001 · Q-B3-03）：邮箱绑定唯一冲突。
    #: 与 ``USERNAME_TAKEN`` 语义不同（用户名 vs 邮箱），**不得复用**。
    EMAIL_TAKEN = "EMAIL_TAKEN"
    # 410
    EXPORT_EXPIRED = "EXPORT_EXPIRED"
    # 422
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PASSWORD_INVALID = "PASSWORD_INVALID"
    # 423
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    # 429
    SESSION_VERIFY_ABORTED = "SESSION_VERIFY_ABORTED"
    # 200（软提示，非错误）
    SOFT_WARNING = "SOFT_WARNING"
    # 5xx
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class FieldErrorCode:
    """**字段级**明细码（S1-B §3.5 ``errors[].code``）。

    与 :class:`ErrorCode`（全局错误码）**不是同一层**：
    全局错误码已冻结为 18 个、**只增不改**；字段级码用于指明"哪个字段、错在哪"，
    仅在 ``errors[]`` 内出现，**不进入全局错误码表**。
    """

    REQUIRED = "REQUIRED"            # 必填缺失
    INVALID_TYPE = "INVALID_TYPE"    # 类型错误
    INVALID_FORMAT = "INVALID_FORMAT"  # 格式非法（用户名等）
    WEAK_PASSWORD = "WEAK_PASSWORD"  # 密码强度不足
    MISMATCH = "MISMATCH"            # 两次输入不一致
    SAME_AS_OLD = "SAME_AS_OLD"      # 新密码与原密码相同
    NOT_ACCEPTED = "NOT_ACCEPTED"    # 协议未勾选


def field_error(field: str, code: str, message: str) -> dict:
    """构造一条字段级明细（``errors[]`` 元素）。"""
    return {"field": field, "code": code, "message": message}



#: 错误码 → HTTP 状态码
ERROR_HTTP_STATUS: dict[str, int] = {
    ErrorCode.INVALID_PARAM: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.CREDENTIALS_INVALID: 401,
    ErrorCode.TOKEN_REUSED: 401,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.USERNAME_TAKEN: 409,
    ErrorCode.GOAL_TYPE_EXISTS: 409,
    ErrorCode.EXPORT_IN_PROGRESS: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.COUNT_MISMATCH: 409,
    ErrorCode.EMAIL_TAKEN: 409,
    ErrorCode.EXPORT_EXPIRED: 410,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.PASSWORD_INVALID: 422,
    ErrorCode.ACCOUNT_LOCKED: 423,
    ErrorCode.SESSION_VERIFY_ABORTED: 429,
    ErrorCode.SOFT_WARNING: 200,  # 软提示：HTTP 200
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}

#: 错误码 → 默认用户可见文案（中性、不含医学判断）
ERROR_MESSAGE: dict[str, str] = {
    ErrorCode.INVALID_PARAM: "请求参数有误，请检查后重试",
    ErrorCode.UNAUTHENTICATED: "登录已过期，请重新登录",
    ErrorCode.CREDENTIALS_INVALID: "用户名或密码错误",
    ErrorCode.TOKEN_REUSED: "登录已过期，请重新登录",
    ErrorCode.RESOURCE_NOT_FOUND: "内容不存在或已被删除",
    ErrorCode.USERNAME_TAKEN: "该用户名已被使用，请更换",
    ErrorCode.GOAL_TYPE_EXISTS: "该类型目标已存在，请编辑现有目标",
    ErrorCode.EXPORT_IN_PROGRESS: "已有导出任务进行中，请稍后",
    ErrorCode.IDEMPOTENCY_CONFLICT: "请求重复，请刷新后重试",
    ErrorCode.COUNT_MISMATCH: "数据已变化，请刷新后重试",
    ErrorCode.EMAIL_TAKEN: "该邮箱已被其他账号使用，请更换",
    ErrorCode.EXPORT_EXPIRED: "导出文件已过期，请重新导出",
    ErrorCode.VALIDATION_FAILED: "请确认是否输错",
    ErrorCode.PASSWORD_INVALID: "密码不正确，请重新输入",
    ErrorCode.ACCOUNT_LOCKED: "账号已临时锁定，请稍后再试",
    ErrorCode.SESSION_VERIFY_ABORTED: "验证失败次数过多，请重新发起",
    ErrorCode.SOFT_WARNING: "该数值超出常见录入范围，请确认是否输错",
    ErrorCode.INTERNAL_ERROR: "服务器繁忙，请稍后重试",
    ErrorCode.SERVICE_UNAVAILABLE: "服务暂时不可用，请稍后重试",
}


class ApiError(Exception):
    """业务异常：由路由/服务层抛出，由统一处理器转换为标准响应。"""

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        http_status: Optional[int] = None,
        data: Any = None,
        errors: Optional[list] = None,
    ) -> None:
        self.code = code
        self.message = message or ERROR_MESSAGE.get(code, "请求处理失败")
        self.http_status = http_status or ERROR_HTTP_STATUS.get(code, 400)
        self.data = data
        #: 字段级明细（可选，仅 VALIDATION_FAILED 等场景使用；不进入全局错误码表）
        self.errors = errors
        super().__init__(self.message)


def validation_error(errors: list, message: Optional[str] = None) -> ApiError:
    """构造 ``422 VALIDATION_FAILED``（携带字段级明细）。"""
    return ApiError(ErrorCode.VALIDATION_FAILED, message=message, errors=errors)


def register_error_handlers(app: Flask) -> None:
    """注册统一错误处理。"""

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):  # noqa: ANN202
        return api_response(
            data=exc.data,
            message=exc.message,
            code=exc.code,
            http_status=exc.http_status,
            errors=exc.errors,
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):  # noqa: ANN202
        mapping = {
            400: ErrorCode.INVALID_PARAM,
            401: ErrorCode.UNAUTHENTICATED,
            404: ErrorCode.RESOURCE_NOT_FOUND,
            405: ErrorCode.INVALID_PARAM,
            409: ErrorCode.IDEMPOTENCY_CONFLICT,
            503: ErrorCode.SERVICE_UNAVAILABLE,
        }
        code = mapping.get(exc.code or 500, ErrorCode.INTERNAL_ERROR)
        return api_response(
            message=ERROR_MESSAGE.get(code, "请求处理失败"),
            code=code,
            http_status=exc.code or 500,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):  # noqa: ANN202
        # 500 不返回任何内部细节；详情仅进服务端日志（经脱敏）
        logger.exception("未处理异常（request_id=%s）", _rid())
        return api_response(
            message=ERROR_MESSAGE[ErrorCode.INTERNAL_ERROR],
            code=ErrorCode.INTERNAL_ERROR,
            http_status=500,
        )


def _rid() -> str:
    from app.core.request_id import get_request_id

    return get_request_id()
