# -*- coding: utf-8 -*-
"""``record_tag`` —— 记录标签（L1，多值属性）。

依据：《S1-B 数据库设计文档》§6.5。

- 心情标签是 V1.0 唯一的「多值」属性（可选多个）。
- **冗余存储 `user_id`**，使标签统计无需 JOIN 主表即可按用户过滤。
- 软删**与主记录同步写入**。
- **不使用 `deleted_marker`**（唯一键 `(record_id, tag_value)` 不含 `is_deleted`，见 §9.2）。
- 本表**无 `updated_at`**。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    BIGINT_UNSIGNED,
    SOFT_DELETE_CHECK,
    TABLE_KWARGS,
    TINYINT_UNSIGNED,
    Base,
)


class RecordTag(Base):
    __tablename__ = "record_tag"
    __table_args__ = (
        Index("uk_record_tag", "record_id", "tag_value", unique=True),
        Index("idx_tag_user", "user_id", "record_id"),
        CheckConstraint(SOFT_DELETE_CHECK, name="ck_record_tag_soft_delete"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    record_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    tag_value: Mapped[str] = mapped_column(String(16), nullable=False)
    is_deleted: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
