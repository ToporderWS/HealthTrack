# -*- coding: utf-8 -*-
"""``user_profile`` —— 健康档案（L1，1:1）。

依据：《S1-B 数据库设计文档》§6.3。

- **不设软删字段**（v1.1 修正）：清空全部数据只清其「健康字段」，档案行**不删除、不软删**。
- **不存 `target_weight_kg`**：目标体重**唯一数据源 = `health_goal`（`goal_type='weight'`）**（D-1 冻结）。
- **不存派生值**（BMI / 年龄）。
- 不存「输入校验区间」常量（属服务端业务规则）。

S4-2 头像（migration ``0002_user_profile_avatar``）：

- ``avatar_key`` **只存服务端生成的 basename**（``secrets.token_hex(16)`` + 扩展名），
  **绝不存绝对路径 / URL / 原始文件名** ⇒ 结构上不可能路径穿越；
- ``avatar_updated_at`` 供缓存失效（``ETag``）与「头像是否已更新」判定；
- ``avatar_url`` / 头像字节数 / MIME **均为派生值 ⇒ 不落库**（一律由 ``avatar_service`` 实时推导）。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BIGINT_UNSIGNED, TABLE_KWARGS, TINYINT_UNSIGNED, Base


class UserProfile(Base):
    __tablename__ = "user_profile"
    __table_args__ = (
        Index("uk_user_profile_user", "user_id", unique=True),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    nickname: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    gender: Mapped[Optional[int]] = mapped_column(TINYINT_UNSIGNED, nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    height_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1), nullable=True)
    initial_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1), nullable=True)
    blood_type: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    medical_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allergy_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    medication_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ── S4-2 头像（migration 0002；**只存 basename**，不存路径 / URL / 原始文件名）──
    avatar_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    avatar_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
