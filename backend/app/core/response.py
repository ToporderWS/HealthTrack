# -*- coding: utf-8 -*-
"""统一响应结构。

依据：《S1-B 第二批 API 接口设计文档》§3.4 / §3.5
统一响应体：``{ code, message, data, request_id }``（失败时**可选追加** ``errors``）

- 成功标识：``code = "OK"``（**不在错误码表内**）
- 错误响应：``code`` 为机器可读错误码，``data`` 通常为 ``null``
- 失败响应在存在**字段级明细**时追加顶层 ``errors`` 数组（§3.5，可选键）
- 软提示 ``SOFT_WARNING`` 使用 **HTTP 200**（不是错误）
"""
from __future__ import annotations

from typing import Any, Optional

from flask import jsonify

from app.core.request_id import REQUEST_ID_HEADER, get_request_id

CODE_OK = "OK"
DEFAULT_OK_MESSAGE = "成功"


def build_body(
    code: str = CODE_OK,
    message: str = DEFAULT_OK_MESSAGE,
    data: Any = None,
    errors: Optional[list] = None,
) -> dict:
    """构造统一响应体。

    冻结口径：
    - **成功** ``{code, message, data, request_id}``（``data`` 键不省略，无数据时为 ``null``）
    - **失败** 同上四键，另在存在字段级明细时**追加** ``errors``
      （S1-B §3.5：``errors`` 为**可选**数组，无字段错误时省略该键）
    """
    body: dict = {"code": code, "message": message}
    if errors:
        body["errors"] = errors
    body["data"] = data
    body["request_id"] = get_request_id()
    return body


def api_response(
    data: Any = None,
    message: str = DEFAULT_OK_MESSAGE,
    code: str = CODE_OK,
    http_status: int = 200,
    errors: Optional[list] = None,
):
    """构造统一响应（自动写入 ``X-Request-Id`` 响应头）。"""
    body = build_body(code=code, message=message, data=data, errors=errors)
    response = jsonify(body)
    response.status_code = http_status
    response.headers[REQUEST_ID_HEADER] = body["request_id"]
    return response


def ok(data: Any = None, message: str = DEFAULT_OK_MESSAGE):
    return api_response(data=data, message=message, code=CODE_OK, http_status=200)


def fail(
    code: str,
    message: str,
    http_status: int,
    data: Optional[Any] = None,
    errors: Optional[list] = None,
):
    return api_response(
        data=data,
        message=message,
        code=code,
        http_status=http_status,
        errors=errors,
    )
