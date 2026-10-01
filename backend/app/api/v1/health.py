# -*- coding: utf-8 -*-
"""Y-01 健康检查（**唯一免鉴权接口**）。

依据：《S1-B 第二批 API 接口设计文档》§12.1

| 项 | 内容 |
|---|---|
| Method / Path | ``GET /api/v1/health`` |
| 鉴权要求 | ❌ **免鉴权** |
| 用途 | 服务存活探测（本机/局域网联调、后续部署探活） |
| 对应 F | **无**（运维能力，不属功能编号） |
| 安全注意 | **只返回** ``{"code":"OK","data":{"status":"up"},"request_id":"..."}``； **不得**返回版本号、环境变量、数据库连接串、服务器时间等任何环境信息 |

> 本接口是 S2 第一批**唯一被实现**的接口；S1-B 冻结的其余 **33 个业务接口不在本批实现**。
"""
from __future__ import annotations

from flask import Blueprint

from app.core.response import ok

bp = Blueprint("health", __name__)


@bp.get("/health")
def health_check():
    """服务存活探测（不返回任何业务 / 环境信息）。"""
    return ok(data={"status": "up"}, message="ok")
