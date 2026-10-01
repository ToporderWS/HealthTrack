# -*- coding: utf-8 -*-
"""健康目标（G-01 / G-02 / G-03）请求 schema。

依据：《S1-B 第二批 API 接口设计文档》§八 G-01 ~ G-03

口径（与第三批一致）：
- 本模块**只做类型层校验**（缺失 / 类型错误 → ``400 INVALID_PARAM``，由
  :func:`app.schemas.base.load_json_b3` 统一抛出）；
- **目标类型 / 周期 / 单位 / 目标值区间 / 字段禁传 / 日期合法性**等语义校验
  在 ``goal_service`` 中完成 → ``422 VALIDATION_FAILED``；
- ``G-03 PATCH`` 为**局部更新**：省略字段 = 不修改（因此**不设** ``load_default``，
  以便区分「未携带」与「显式传 null（清空）」）。
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields


class _GoalBase(Schema):
    class Meta:
        unknown = EXCLUDE


class GoalCreateSchema(_GoalBase):
    """G-02 ``POST /api/v1/goals`` 请求体。

    ``period_type`` / ``unit`` 由**服务端按 goal_type 强制填充**；客户端若传入，
    必须与服务端取值一致（不一致 → 422）。
    **不接受任何"系统推荐值"参数**（红线：目标值一律用户自设）。
    """

    goal_type = fields.String(required=True)
    period_type = fields.String(allow_none=True)
    target_value = fields.Number(required=True, allow_none=True)
    unit = fields.String(allow_none=True)
    attr_1 = fields.String(allow_none=True)
    start_date = fields.String(allow_none=True)
    target_date = fields.String(allow_none=True)
    start_weight_kg = fields.Number(allow_none=True)
    auto_start_weight = fields.Boolean(load_default=False)
    acknowledge_warnings = fields.Boolean(load_default=False)


class GoalPatchSchema(_GoalBase):
    """G-03 ``PATCH /api/v1/goals/{id}`` 请求体（局部更新）。

    ``goal_type`` 一旦出现（**即使值相同**）→ ``422``（类型不同即"另一个目标"）；
    ``start_weight_kg`` 出现即 ``422``（起始快照一经创建即冻结）。
    """

    goal_type = fields.String(allow_none=True)
    target_value = fields.Number(allow_none=True)
    unit = fields.String(allow_none=True)
    attr_1 = fields.String(allow_none=True)
    start_date = fields.String(allow_none=True)
    target_date = fields.String(allow_none=True)
    start_weight_kg = fields.Number(allow_none=True)
    acknowledge_warnings = fields.Boolean(load_default=False)


__all__ = ["GoalCreateSchema", "GoalPatchSchema"]
