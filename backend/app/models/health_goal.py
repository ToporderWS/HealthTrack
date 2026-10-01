# -*- coding: utf-8 -*-
"""``health_goal`` —— 健康目标（L1）。

依据：《S1-B 数据库设计文档》§6.6。

- `goal_type` ∈ {weight, water, sport, sleep}（V1.0 仅此 4 类）。
- **目标值一律由用户自设**；系统**不提供任何医学推荐值 / 默认阈值**，也不落「系统推荐值」字段。
- **`goal_type='weight'` 是「目标体重」的唯一数据源**（D-1 冻结）。
- 删除走软删；**本表是 V1.0 唯一需要 `deleted_marker` 的表**（用于释放唯一约束，支持软删后重建）。
- `status`：1=进行中，0=已暂停（F-045 冻结「允许暂停而非删除」）。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    BIGINT_UNSIGNED,
    SOFT_DELETE_CHECK,
    TABLE_KWARGS,
    TINYINT_UNSIGNED,
    Base,
)


class HealthGoal(Base):
    __tablename__ = "health_goal"
    __table_args__ = (
        Index("uk_goal_user_type_active", "user_id", "goal_type", "deleted_marker", unique=True),
        CheckConstraint(SOFT_DELETE_CHECK, name="ck_health_goal_soft_delete"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    goal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    period_type: Mapped[str] = mapped_column(String(8), nullable=False)
    target_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(12), nullable=False)
    attr_1: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    start_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("1")
    )
    is_deleted: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_marker: Mapped[int] = mapped_column(
        BIGINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
