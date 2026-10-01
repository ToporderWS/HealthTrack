# -*- coding: utf-8 -*-
"""首页 / 统计 / 趋势 API（本批实现 **S-01 ~ S-03**）。

依据：《S1-B 第二批 API 接口设计文档》§九（模块 S）

| API | Method / Path | 鉴权 | 对应 F |
|---|---|---|---|
| S-01 | ``GET /api/v1/home/overview`` | ✅ | F-010 / F-012 / F-013 |
| S-02 | ``GET /api/v1/stats/trend`` | ✅ | F-031 ~ F-034 / F-036 |
| S-03 | ``GET /api/v1/stats/summary`` | ✅ | F-035 / F-046 |

> 本模块**只承载协议与边界**；聚合口径在 ``app/services/stats_service.py``。
> ``user_id`` **只来自 Access Token**；客户端以任何方式提交 ``user_id`` → 全局守卫 ``400``。
> 三接口**均不分页、均无请求体**（仅 GET + query 参数）。
> **不返回**任何医学判断 / 评价 / 参考范围 / 红绿语义（红线约束：非医学输出，仅陈述事实）。
"""
from __future__ import annotations

from flask import Blueprint, request

from app.core.auth import current_user_id, require_auth
from app.core.db import get_db
from app.core.response import ok
from app.services import stats_service

bp = Blueprint("stats", __name__)


@bp.get("/home/overview")
@require_auth
def home_overview():
    """S-01 首页概览（今日概览 + 目标环 + 最近 10 条 + 提醒兜底占位）。"""
    return ok(data=stats_service.home_overview(get_db(), current_user_id(), request.args),
              message="成功")


@bp.get("/stats/trend")
@require_auth
def stats_trend():
    """S-02 趋势数据（8 指标 × 7/30/90 窗口；缺失日期不补零）。"""
    return ok(data=stats_service.trend(get_db(), current_user_id(), request.args),
              message="成功")


@bp.get("/stats/summary")
@require_auth
def stats_summary():
    """S-03 统计摘要（5 项数字 + 各指标差异字段）。"""
    return ok(data=stats_service.summary(get_db(), current_user_id(), request.args),
              message="成功")


__all__ = ["bp"]
