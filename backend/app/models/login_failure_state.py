# -*- coding: utf-8 -*-
"""``login_failure_state`` —— 登录失败与锁定状态（L2）。

依据：《S1-B 数据库设计文档》§6.8。

- `username` **统一小写**；**对「不存在的用户名」同样落行** → 保证锁定行为对
  「账号是否存在」完全一致（**防账号枚举**）。
- 持久化理由：重启服务后计数与锁定状态不丢失。
- 本表**不含软删字段**；**本表无 `created_at`**（只有 `updated_at`）。

冻结规则 → 字段映射（完整算法见 S1-B §7.4，本批不实现业务逻辑）：
| 连续失败 5 次 → `fail_count` 达 5 触发锁定 |
| 首次锁 5 分钟 → `locked_until = NOW() + 5min`，`lock_level = 1` |
| 24h 内二次 → 15 分钟（`lock_level = 2`）；三次及以上 → 60 分钟（`lock_level = 3`，上限） |
| 成功登录 / 锁定期满 → 清零 |
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    BIGINT_UNSIGNED,
    TABLE_KWARGS,
    TINYINT_UNSIGNED,
    Base,
)


class LoginFailureState(Base):
    __tablename__ = "login_failure_state"
    __table_args__ = (
        Index("uk_login_fail_username", "username", unique=True),
        Index("idx_login_fail_locked", "locked_until"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(20), nullable=False)
    fail_count: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    first_fail_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    lock_level: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
