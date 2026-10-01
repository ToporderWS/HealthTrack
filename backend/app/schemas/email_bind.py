# -*- coding: utf-8 -*-
"""邮箱绑定模块请求体 Schema（**B3**：PR-04 / PR-05）。

依据
----
- 《忘记密码自助找回 · B3 开工前只读预检与实施方案》§7 方案甲 / §8.2 契约表 / §10 安全模型；
- 需求方 B3 授权（2026-09-24）§二（请求模型）＋ §五（安全要求）。

分层口径（与 ``schemas/auth.py`` / ``schemas/password_reset.py`` 一致）
----------------------------------------------------------------------
- 本层只做「存在性 + 类型」校验（缺失 / 类型错 → ``400 INVALID_PARAM``）；
- **语义规则**（邮箱格式、当前密码是否正确、验证码是否正确、唯一冲突）由
  ``services/email_bind_service.py`` 判定 → ``422`` / ``409`` / ``429``。

⚠️ 两个 schema **只声明契约字段**并用 ``unknown = EXCLUDE``：
- 两个接口**都不接受** ``user_id``（身份只能来自当前登录态）；
  即便写了，也会被全局身份守卫拦成 ``400 INVALID_PARAM``（``core/auth.py``）；
- 也**不接受** ``purpose`` / ``code_hash`` 等内部字段 ⇒ 客户端无法指定 ``purpose``
  （即无法把 ``email_bind`` 的码「挪去」通过 ``password_reset`` 校验）。
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields


class EmailBindRequestSchema(Schema):
    """PR-04 发起邮箱绑定（需登录）。

    | 字段 | 必填 | 说明 |
    |---|---|---|
    | ``email`` | ✅ | 待绑定 / 待改绑的目标邮箱（服务端规范化 + 格式校验） |
    | ``current_password`` | ✅ | **当前密码**（邮箱是密码找回安全因子 ⇒ 敏感操作需复验） |
    """

    class Meta:
        unknown = EXCLUDE

    email = fields.String(required=True)
    current_password = fields.String(required=True)


class EmailBindConfirmSchema(Schema):
    """PR-05 校验绑定验证码并落库（需登录）。

    | 字段 | 必填 | 说明 |
    |---|---|---|
    | ``email`` | ✅ | 必须与本次挑战的目标邮箱**完全一致**（大小写 / 空白经规范化后比对） |
    | ``code`` | ✅ | 邮件中的 6 位数字验证码 |
    | ``current_password`` | ✅ | **当前密码**（与 PR-04 同口径复验） |
    """

    class Meta:
        unknown = EXCLUDE

    email = fields.String(required=True)
    code = fields.String(required=True)
    current_password = fields.String(required=True)


__all__ = ["EmailBindRequestSchema", "EmailBindConfirmSchema"]
