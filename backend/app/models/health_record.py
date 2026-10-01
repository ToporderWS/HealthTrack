# -*- coding: utf-8 -*-
"""``health_record`` —— 健康记录（L1，单表 + 指标类型字段）。

依据：《S1-B 数据库设计文档》§6.4 / §7.1。

- 采用 **单表 + `metric_type`**（8 类 P0 指标：weight / bp / heart / glucose / sleep / water / sport / mood）。
- **不使用 `deleted_marker`**（本表无唯一约束需求）。
- **派生值不落库**（BMI / 睡眠时长 / 累计值）。
- `recorded_at` = 测量/发生时点；睡眠指标中 = **起床时间**（S0 9.4 跨天归属口径）。
- `time_start` **仅睡眠使用**，其他指标恒为 NULL。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    desc,
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


class HealthRecord(Base):
    __tablename__ = "health_record"
    __table_args__ = (
        # 趋势 / 记录历史 / 数据总览 / 批量删除
        Index("idx_hr_user_metric_time", "user_id", "metric_type", desc("recorded_at")),
        # 首页最近 10 条 / 今日统计 / 导出全量 / 清空数据
        Index("idx_hr_user_time", "user_id", desc("recorded_at")),
        # 30 天物理清理（全局维护任务）
        Index("idx_hr_cleanup", "is_deleted", "deleted_at"),
        CheckConstraint(SOFT_DELETE_CHECK, name="ck_health_record_soft_delete"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    metric_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    value_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    value_3: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    unit: Mapped[str] = mapped_column(String(12), nullable=False)
    attr_1: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    attr_2: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    time_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_deleted: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
