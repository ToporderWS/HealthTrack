# -*- coding: utf-8 -*-
"""档案（P-01 / P-02）请求 schema。

依据：《S1-B 第二批 API 接口设计文档》§六 P-02「请求参数（整体替换语义：省略即置空）」

口径：
- **本模块只做类型层校验**（缺失 / 类型错误 → ``400``，由 :func:`load_json_b3` 统一抛出）；
- **长度 / 枚举 / 区间 / 日期合法性**等语义校验在 ``profile_service`` 中完成 → ``422 VALIDATION_FAILED``；
- `PUT` 为**整体替换**：省略字段即置空（``load_default=None``）。
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields


class ProfileUpdateSchema(Schema):
    """P-02 ``PUT /api/v1/profile`` 请求体。"""

    class Meta:
        unknown = EXCLUDE

    nickname = fields.String(allow_none=True, load_default=None)
    gender = fields.Integer(allow_none=True, load_default=None)
    birth_date = fields.String(allow_none=True, load_default=None)
    height_cm = fields.Number(allow_none=True, load_default=None)
    initial_weight_kg = fields.Number(allow_none=True, load_default=None)
    blood_type = fields.String(allow_none=True, load_default=None)
    medical_history = fields.String(allow_none=True, load_default=None)
    allergy_history = fields.String(allow_none=True, load_default=None)
    medication_notes = fields.String(allow_none=True, load_default=None)
    acknowledge_warnings = fields.Boolean(load_default=False)


__all__ = ["ProfileUpdateSchema"]
