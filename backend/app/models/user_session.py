# -*- coding: utf-8 -*-
"""``user_session`` —— 用户会话 / Token 状态（L2）。

依据：《S1-B 数据库设计文档》§6.7。

支撑冻结口径：
- Token 有效期（访问 **2h** / 刷新 **30d**）
- 退出登录**仅失效当前 Token**
- 改密后**全部旧 Token 立即失效**
- 「**同一会话内**」的导出 / 改密验密失败计数（放账号表会变成跨会话累计，与冻结口径不符）

本表**不含软删字段**；**本表不存 Token 明文**（只存 SHA-256 哈希）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CHAR, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BIGINT_UNSIGNED, TABLE_KWARGS, TINYINT_UNSIGNED, Base


class UserSession(Base):
    __tablename__ = "user_session"
    __table_args__ = (
        Index("uk_session_refresh", "refresh_token_hash", unique=True),
        Index("idx_session_user", "user_id", "revoked_at"),
        Index("idx_session_access", "access_token_id"),
        Index("idx_session_refresh_exp", "refresh_expires_at"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    access_token_id: Mapped[Optional[str]] = mapped_column(CHAR(64), nullable=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    export_pwd_fail_count: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    change_pwd_fail_count: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
