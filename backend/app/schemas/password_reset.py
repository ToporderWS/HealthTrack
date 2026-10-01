# -*- coding: utf-8 -*-
"""找回密码模块请求体 Schema（**B2**：PR-01 / PR-02 / PR-03）。

依据：《忘记密码自助找回 · 开工前只读审计与方案报告》§6.2 接口契约。

分层口径（与 ``schemas/auth.py`` 一致）
-------------------------------------
- 本层只做「存在性 + 类型」校验（缺失 / 类型错 → ``400 INVALID_PARAM``）；
- **语义规则**（验证码正确性、密码强度、两次一致、凭证有效性）由
  ``services/password_reset_service.py`` 判定 → ``422`` / ``401`` / ``429``。

⚠️ 三个 schema 都**只声明契约字段**并用 ``unknown = EXCLUDE``：
PR-01 尤其重要 —— **不得**接受 ``email`` 等任何额外字段，
否则等于开了「未绑定邮箱的老用户临时指定新邮箱」的口子（B2 授权 §五.3 明令禁止）。
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields


class PasswordResetRequestSchema(Schema):
    """PR-01 请求密码找回。

    **只有** ``username``：不接受 ``email`` / ``user_id`` / ``reset_token`` 等任何额外字段。
    """

    class Meta:
        unknown = EXCLUDE

    username = fields.String(required=True)


class PasswordResetVerifySchema(Schema):
    """PR-02 校验验证码。"""

    class Meta:
        unknown = EXCLUDE

    username = fields.String(required=True)
    code = fields.String(required=True)


class PasswordResetConfirmSchema(Schema):
    """PR-03 设置新密码（``reset_token`` 在**请求体**，不是 Bearer）。"""

    class Meta:
        unknown = EXCLUDE

    reset_token = fields.String(required=True)
    new_password = fields.String(required=True)
    confirm_password = fields.String(required=True)


__all__ = [
    "PasswordResetRequestSchema",
    "PasswordResetVerifySchema",
    "PasswordResetConfirmSchema",
]
