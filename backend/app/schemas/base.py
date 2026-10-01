# -*- coding: utf-8 -*-
"""S2 第三批请求解析与字段级明细（**独立于第二批已封板实现**）。

为什么单独一份：
- 第二批的 ``app/schemas/common.py`` 属**已封板成果**，本批**不修改**；
- 本批（P / R 模块）新增字段的中文标签在**本模块**登记，``errors[]`` 构码口径
  与第二批**完全一致**（复用 :class:`~app.core.errors.FieldErrorCode`，**不扩充**）。

分层口径（与第二批一致）：
- **参数缺失 / 类型错误** → ``400 INVALID_PARAM``（携带 ``errors[]``）
- **语义非法**（枚举非法、不可能值、字段矛盾、禁止字段）→ ``422 VALIDATION_FAILED``
- **疑似录入错误**（不能证明其错）→ 独立 ``warnings[]`` 体系（``app.core.warnings``）
"""
from __future__ import annotations

from typing import Any, Dict

from flask import request
from marshmallow import Schema, ValidationError

from app.core.errors import ApiError, ErrorCode, FieldErrorCode, field_error
from app.schemas.common import label_of

#: 第三批新增字段 → 中性中文标签（**不含任何评价性表述**）
FIELD_LABEL_B3: Dict[str, str] = {
    # ── 通用 ──
    "metric_type": "指标类型",
    "value_1": "数值",
    "value_2": "数值",
    "value_3": "数值",
    "unit": "单位",
    "attr_1": "选项",
    "attr_2": "选项",
    "recorded_at": "记录时间",
    "time_start": "入睡时间",
    "tags": "标签",
    "note": "备注",
    "acknowledge_warnings": "确认标记",
    # ── 档案 ──
    "nickname": "昵称",
    "gender": "性别",
    "birth_date": "出生日期",
    "height_cm": "身高",
    "initial_weight_kg": "初始体重",
    "blood_type": "血型",
    "medical_history": "健康背景记录",
    "allergy_history": "过敏记录",
    "medication_notes": "药物输入记录",
    # ── 查询 / 批量 ──
    "start": "开始时间",
    "end": "结束时间",
    "limit": "每页条数",
    "cursor": "分页游标",
    "expected_count": "条数",
    "confirm_text": "确认文字",
    # ── 健康目标（S2 第四批 G-01~G-07；**仅追加键值**） ──
    "goal_type": "目标类型",
    "period_type": "周期类型",
    "target_value": "目标值",
    "start_date": "开始日期",
    "target_date": "目标日期",
    "start_weight_kg": "起始体重",
    "auto_start_weight": "自动取起始体重",
    "goal_id": "目标",
    "rate_window": "统计窗口",
}


def label3(field: str) -> str:
    """字段标签（本批登记优先，未登记时回落到第二批标签表）。"""
    return FIELD_LABEL_B3.get(field) or label_of(field)


def load_json_b3(schema: Schema) -> Dict[str, Any]:
    """解析 JSON 请求体并按 schema 校验（口径与第二批一致）。"""
    if not request.is_json:
        raise ApiError(ErrorCode.INVALID_PARAM)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)

    try:
        return schema.load(body)
    except ValidationError as exc:
        errors = []
        for field, msgs in (exc.messages or {}).items():
            first = msgs[0] if isinstance(msgs, list) and msgs else msgs
            text = str(first)
            if text.startswith("Missing"):
                errors.append(
                    field_error(field, FieldErrorCode.REQUIRED, f"{label3(field)}不能为空")
                )
            else:
                errors.append(
                    field_error(field, FieldErrorCode.INVALID_TYPE, f"{label3(field)}格式不正确")
                )
        raise ApiError(ErrorCode.INVALID_PARAM, errors=errors or None)


__all__ = ["load_json_b3", "label3", "FIELD_LABEL_B3"]
