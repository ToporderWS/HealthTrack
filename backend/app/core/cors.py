# -*- coding: utf-8 -*-
"""H5 开发环境跨源（CORS）支持 —— **仅 APP_ENV=development 生效**。

背景：
    H5 dev server（``http://localhost:5173``）与 Flask（``http://127.0.0.1:5000``）
    属**不同源**；前端统一请求封装发送 ``Content-Type: application/json``，
    属非简单请求，浏览器会先发 ``OPTIONS`` 预检。预检响应缺少
    ``Access-Control-Allow-Origin`` 时，浏览器直接拦截实际 POST
    （报 CORS 错误，非 ``ERR_CONNECTION_REFUSED``）。

本模块的刻意约束（属设计要求，勿放宽）：
1. **只在 ``APP_ENV=development`` 时注册**；``test`` / ``production`` 下
   :func:`register_dev_cors` 直接返回，**不注册任何钩子**。
2. **不使用 ``Access-Control-Allow-Origin: *``**：仅当请求 ``Origin``
   精确命中白名单 :data:`DEV_CORS_ORIGINS` 时才回显该源。
3. **不引入 ``flask-cors``**，仅使用 Flask 原生 ``after_request``。
4. 不写日志、不写库、不读请求体、不触碰任何业务逻辑与状态。
5. 只影响**响应头**，不改变任何响应体、状态码、路由与错误码。

变更提示：白名单如需增源（如局域网真机调试），属**新变更**，须走授权流程后修改
:data:`DEV_CORS_ORIGINS`，**不得**在运行期从外部注入通配来源。
"""
from __future__ import annotations

from flask import Flask, request

#: 允许携带跨源请求的 H5 开发源（**仅 development**）；
#: 含开发机局域网源（S3-9 3.3 真机联调：手机经 http://192.168.1.8:5173 访问 H5）。
DEV_CORS_ORIGINS = ("http://localhost:5173", "http://192.168.1.8:5173")

#: 允许的请求方法（覆盖 /api/v1 全部已冻结业务方法）
DEV_CORS_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

#: 兜底允许的请求头（实际以前端预检请求的 Access-Control-Request-Headers 为准回显）
DEV_CORS_HEADERS = "Content-Type, Authorization, Idempotency-Key, X-Request-Id"

#: 允许浏览器读取的响应头（request.js 会读取响应体 request_id，
#: 此处仅放开调试用响应头，不放开任何其他头）
DEV_CORS_EXPOSE_HEADERS = "X-Request-Id"

#: 预检结果缓存时间（秒）
DEV_CORS_MAX_AGE = "600"


def register_dev_cors(app: Flask) -> None:
    """注册 development 专用的 CORS 响应头钩子；非 development 时为 no-op。"""
    if str(app.config.get("APP_ENV") or "").strip().lower() != "development":
        return

    @app.after_request
    def _apply_dev_cors(response):  # noqa: ANN001, ANN202
        """为白名单来源的响应补 CORS 头（含 OPTIONS 预检与全部业务响应）。"""
        origin = request.headers.get("Origin")
        if origin in DEV_CORS_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = DEV_CORS_METHODS
            # 优先回显浏览器的预检请求头，避免遗漏前端实际发送的头
            response.headers["Access-Control-Allow-Headers"] = (
                request.headers.get("Access-Control-Request-Headers")
                or DEV_CORS_HEADERS
            )
            response.headers["Access-Control-Expose-Headers"] = (
                DEV_CORS_EXPOSE_HEADERS
            )
            response.headers["Access-Control-Max-Age"] = DEV_CORS_MAX_AGE
            # 同一 URL 的响应随 Origin 变化，避免被共享缓存串味
            response.headers.add("Vary", "Origin")
        return response


__all__ = [
    "register_dev_cors",
    "DEV_CORS_ORIGINS",
    "DEV_CORS_METHODS",
    "DEV_CORS_HEADERS",
    "DEV_CORS_EXPOSE_HEADERS",
    "DEV_CORS_MAX_AGE",
]
