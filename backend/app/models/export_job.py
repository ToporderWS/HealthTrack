# -*- coding: utf-8 -*-
"""``export_job`` —— 数据导出任务与临时文件（L3）。

依据：《S1-B 数据库设计文档》§6.9。

- 下载凭证 `file_token` **不暴露服务器路径**；`file_path` **永不返回给客户端**。
- `download_expires_at` = 生成 + **10 分钟**；`purge_at` = 生成 + **60 分钟**（强制清理）。
- 本表**不含软删字段**。
- **不做小范围豁免**：任何导出一律二次验密（S1-A 冻结）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CHAR, DateTime, Index, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BIGINT_UNSIGNED, INT_UNSIGNED, TABLE_KWARGS, Base


class ExportJob(Base):
    __tablename__ = "export_job"
    __table_args__ = (
        Index("uk_export_token", "file_token", unique=True),
        Index("idx_export_user", "user_id", desc("created_at")),
        Index("idx_export_purge", "purge_at", "status"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    metric_types: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    range_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    range_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    file_token: Mapped[str] = mapped_column(CHAR(32), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(INT_UNSIGNED, nullable=True)
    record_count: Mapped[Optional[int]] = mapped_column(INT_UNSIGNED, nullable=True)
    download_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    purge_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
