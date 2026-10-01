# -*- coding: utf-8 -*-
"""健康记录（R-01 / R-04 / R-06）请求 schema。

依据：《S1-B 第二批 API 接口设计文档》§七 R-01 / R-04 / R-06

口径：
- 本模块**只做类型层校验**（缺失 / 类型错误 → ``400 INVALID_PARAM``）；
- **指标必填矩阵 / 枚举 / 数值区间 / 字段矛盾** → ``422 VALIDATION_FAILED``（在 ``record_service`` 判定）；
- ``R-04 PATCH`` 为**局部更新**：省略字段 = 不修改（因此**不设** ``load_default``，
  以便区分「未携带」与「显式传 null（清空）」）。
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields


class _RecordBase(Schema):
    class Meta:
        unknown = EXCLUDE


class RecordCreateSchema(_RecordBase):
    """R-01 ``POST /api/v1/records`` 请求体。"""

    metric_type = fields.String(required=True)
    value_1 = fields.Number(allow_none=True)
    value_2 = fields.Number(allow_none=True)
    value_3 = fields.Number(allow_none=True)
    unit = fields.String(allow_none=True)
    attr_1 = fields.String(allow_none=True)
    attr_2 = fields.String(allow_none=True)
    recorded_at = fields.String(allow_none=True)
    time_start = fields.String(allow_none=True)
    tags = fields.List(fields.String(), allow_none=True)
    note = fields.String(allow_none=True)
    acknowledge_warnings = fields.Boolean(load_default=False)


class RecordPatchSchema(_RecordBase):
    """R-04 ``PATCH /api/v1/records/{id}`` 请求体。

    ``metric_type`` 一旦出现（**即使值相同**）→ ``422``（§七 R-04：语义上"换指标"应删除后新建）。
    """

    metric_type = fields.String(allow_none=True)
    value_1 = fields.Number(allow_none=True)
    value_2 = fields.Number(allow_none=True)
    value_3 = fields.Number(allow_none=True)
    unit = fields.String(allow_none=True)
    attr_1 = fields.String(allow_none=True)
    attr_2 = fields.String(allow_none=True)
    recorded_at = fields.String(allow_none=True)
    time_start = fields.String(allow_none=True)
    tags = fields.List(fields.String(), allow_none=True)
    note = fields.String(allow_none=True)
    acknowledge_warnings = fields.Boolean(load_default=False)


class BatchDeleteSchema(_RecordBase):
    """R-06 ``POST /api/v1/records/batch-delete`` 请求体。"""

    metric_type = fields.String(allow_none=True)
    start = fields.String(allow_none=True)
    end = fields.String(allow_none=True)
    password = fields.String(required=True)
    expected_count = fields.Integer(allow_none=True)
    confirm_text = fields.String(allow_none=True)
    acknowledge_warnings = fields.Boolean(allow_none=True)


__all__ = ["RecordCreateSchema", "RecordPatchSchema", "BatchDeleteSchema"]
