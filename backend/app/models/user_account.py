# -*- coding: utf-8 -*-
"""``user_account`` —— 用户账号（L2）。

依据：《S1-B 数据库设计文档》§6.2。
本表**不设软删字段**（注销 = 物理删除，无「软删账号」中间态）；
**不设 status / last_login_at**（V1.0 无管理员、无该展示需求）。

migration ``0003_password_reset_email``（``CR-F006-001`` · 2026-09-23 B1）
----------------------------------------------------------------------
新增 2 列 + 1 唯一索引 + 1 CHECK，**全部向后兼容存量账号**：

- ``email``：**只存「已验证」邮箱**（canonical = ``strip().lower()``，见
  ``core.password_reset.normalize_email``）。
  **待验证邮箱不占本列** —— 它只存在于 ``verification_code`` 挑战记录中。
  这样做的理由：若「待验证地址」也占唯一约束，攻击者可用**自己并不拥有**的地址
  抢先占位，使真正的地址所有者在绑定/找回时被永久拒绝（**地址抢占型 DoS**）。
- ``email_verified_at``：与 ``email`` **同时为空 / 同时非空**（DB 级 CHECK 强制）。
- ``uk_user_account_email``：唯一索引。MySQL 唯一索引对 ``NULL`` **不去重**
  （已实测：3 行 ``NULL`` 可共存）⇒ **存量 6 个 ``email=NULL`` 账号完全不受影响**。
  列级排序规则 ``utf8mb4_0900_as_ci`` = **大小写不敏感 + 重音敏感**：
  即使在应用层规范化回归的情况下 ``A@B.com`` 也无法与 ``a@b.com`` 并存（DB 级二次防线），
  同时不误伤 ``café@x.com`` / ``cafe@x.com`` 这类**合法不同**地址（已实测）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BIGINT_UNSIGNED, TABLE_KWARGS, Base

#: 邮箱长度上限（RFC 5321 = 254；与 ``core.password_reset.EMAIL_MAX_LEN`` 同口径）
EMAIL_MAX_LEN = 254
#: 邮箱列**列级**排序规则（覆盖表级 ``utf8mb4_0900_ai_ci``）：
#: 大小写不敏感（防大小写变体绕过唯一性） + 重音敏感（不误伤合法不同地址）。
EMAIL_COLLATION = "utf8mb4_0900_as_ci"
#: 「``email`` 与 ``email_verified_at`` 必须同时为空 / 同时非空」的 DB 级不变量。
#: ⇒ 结构上不存在「有邮箱但未验证」与「已验证但无邮箱」两种非法中间态。
EMAIL_PAIR_CHECK = (
    "(email IS NULL AND email_verified_at IS NULL) "
    "OR (email IS NOT NULL AND email_verified_at IS NOT NULL)"
)


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        Index("uk_user_account_username", "username", unique=True),
        Index("uk_user_account_email", "email", unique=True),
        CheckConstraint(EMAIL_PAIR_CHECK, name="ck_user_account_email_pair"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    password_algo: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'bcrypt'")
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'user'")
    )
    terms_agreed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    agreement_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # ── migration 0003（CR-F006-001）：**只存已验证邮箱**；待验证地址在
    #    ``verification_code`` 挑战记录中，不占本列（防地址抢占）──
    email: Mapped[Optional[str]] = mapped_column(
        String(EMAIL_MAX_LEN, collation=EMAIL_COLLATION), nullable=True
    )
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
