# -*- coding: utf-8 -*-
"""``request_id`` 生成与注入。

依据：《S1-B 第二批 API 接口设计文档》§3.7 request_id 使用规则
- 生成方：**服务端**（即使客户端携带也不直接采信）
- 格式：32 位十六进制，每次请求唯一
- 返回位置：响应体 ``request_id`` + 响应头 ``X-Request-Id``
- 禁止：不得作为用户标识；日志中不得与 user_id / 用户名 / 健康数值同时出现
"""
from __future__ import annotations

import re
import uuid

from flask import Flask, g

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def generate_request_id() -> str:
    """生成 32 位十六进制 request_id。"""
    return uuid.uuid4().hex


def get_request_id() -> str:
    """取当前请求的 request_id；若不存在则即时生成（如错误发生在 before_request 之前）。"""
    rid = getattr(g, "request_id", None)
    if not rid:
        rid = generate_request_id()
        g.request_id = rid
    return rid


def register_request_id(app: Flask) -> None:
    """注册 request_id 的生成与回写钩子。"""

    @app.before_request
    def _assign_request_id():  # noqa: ANN202
        # 服务端生成，不采信客户端传入值（§3.7）
        g.request_id = generate_request_id()

    @app.after_request
    def _attach_request_id(response):  # noqa: ANN001, ANN202
        response.headers[REQUEST_ID_HEADER] = get_request_id()
        return response
