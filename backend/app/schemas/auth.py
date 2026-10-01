# -*- coding: utf-8 -*-
"""认证模块请求体 Schema（仅做「存在性 + 类型」校验）。

依据：《S1-B 第二批 API 接口设计文档》§五 A-01 ~ A-06 请求参数表。

> 语义规则（用户名格式、密码强度、协议必须勾选、两次密码一致等）**不在此层**，
> 由 ``app/services/auth_service.py`` 统一判定 → ``422 VALIDATION_FAILED``。
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields


class RegisterSchema(Schema):
    """A-01 注册。"""

    class Meta:
        unknown = EXCLUDE

    username = fields.String(required=True)
    password = fields.String(required=True)
    agreement_version = fields.String(required=True)
    agreement_accepted = fields.Boolean(required=True)
    auto_login = fields.Boolean(load_default=True)  # 默认 true（契约冻结）


class LoginSchema(Schema):
    """A-02 登录。"""

    class Meta:
        unknown = EXCLUDE

    username = fields.String(required=True)
    password = fields.String(required=True)


class RefreshSchema(Schema):
    """A-03 刷新 Token。"""

    class Meta:
        unknown = EXCLUDE

    refresh_token = fields.String(required=True)


class ChangePasswordSchema(Schema):
    """A-05 修改密码。"""

    class Meta:
        unknown = EXCLUDE

    old_password = fields.String(required=True)
    new_password = fields.String(required=True)
    confirm_password = fields.String(required=True)


__all__ = ["RegisterSchema", "LoginSchema", "RefreshSchema", "ChangePasswordSchema"]
