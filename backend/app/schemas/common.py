# -*- coding: utf-8 -*-
"""请求体解析与字段级错误构造（Marshmallow 薄封装）。

分层口径（S1-B §3.5 / §3.6）：
- **参数缺失 / 类型错误** → ``400 INVALID_PARAM``（携带 ``errors[]`` 字段明细）
- **语义非法**（格式不合规、强度不足、不一致、未勾选协议等）→ ``422 VALIDATION_FAILED``
  （由服务层判定并抛出，见 ``app/services/auth_service.py``）

> ``errors[]`` 使用 :class:`~app.core.errors.FieldErrorCode` 字段级码，
> **与冻结的 18 个全局错误码不是同一层**。
"""
from __future__ import annotations

from typing import Any, Dict

from marshmallow import Schema, ValidationError
from flask import request

from app.core.errors import ApiError, ErrorCode, FieldErrorCode, field_error

#: 字段名 → 中文标签（用于拼装中性提示文案；**不涉及任何健康/医学表述**）
FIELD_LABEL: Dict[str, str] = {
    "username": "用户名",
    "password": "密码",
    "agreement_version": "协议版本",
    "agreement_accepted": "协议同意状态",
    "auto_login": "自动登录",
    "refresh_token": "刷新令牌",
    "old_password": "原密码",
    "new_password": "新密码",
    "confirm_password": "确认密码",
    # ── B2 找回密码（PR-01 / PR-02 / PR-03）──
    "code": "验证码",
    "reset_token": "重置凭证",
    # ── B3 邮箱绑定（PR-04 / PR-05）──
    "email": "邮箱",
    "current_password": "当前密码",
}


def label_of(field: str) -> str:
    return FIELD_LABEL.get(field, field)


def load_json(schema: Schema) -> Dict[str, Any]:
    """解析 JSON 请求体并按 schema 校验。

    - 非 JSON / 非对象 / 解析失败 → ``400 INVALID_PARAM``
    - 字段缺失 / 类型错误 → ``400 INVALID_PARAM``（附 ``errors[]``）
    """
    if not request.is_json:
        raise ApiError(ErrorCode.INVALID_PARAM)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)

    try:
        return schema.load(body)
    except ValidationError as exc:
        errors = []
        messages = exc.messages or {}
        for field, msgs in messages.items():
            first = msgs[0] if isinstance(msgs, list) and msgs else msgs
            text = str(first)
            if text.startswith("Missing"):
                errors.append(
                    field_error(field, FieldErrorCode.REQUIRED, f"{label_of(field)}不能为空")
                )
            else:
                errors.append(
                    field_error(
                        field, FieldErrorCode.INVALID_TYPE, f"{label_of(field)}格式不正确"
                    )
                )
        raise ApiError(ErrorCode.INVALID_PARAM, errors=errors or None)


__all__ = ["load_json", "label_of", "FIELD_LABEL"]
