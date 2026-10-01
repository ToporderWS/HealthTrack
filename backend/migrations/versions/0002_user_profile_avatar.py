# -*- coding: utf-8 -*-
"""S4-2 头像上传：``user_profile`` 新增 2 列

Revision ID: 0002_user_profile_avatar
Revises: 0001_initial_schema
Create Date: 2026-09-22

严格依据：《康迹 HealthTrack · S4-2A 头像上传技术方案与开工前审计报告》§二 DB 设计
（需求方 2026-09-22 正式授权 G2）。

**只允许**增加 2 列：

- ``avatar_key VARCHAR(64) NULL`` —— **只存服务端生成的 basename**（32 位十六进制 + 扩展名），
  **绝不存绝对路径 / URL**（结构上不可能路径穿越；DB 泄露也不构成文件系统越界）
- ``avatar_updated_at DATETIME NULL`` —— 供缓存失效 / `ETag` 与前端「头像已更新」判定

**禁止其它 schema 漂移**：

- **0 新表**、**0 新索引**、**0 外键**、0 列改名、0 列删除、0 类型变更；
- 不加 ``avatar_url`` / ``avatar_size_bytes`` / ``avatar_mime``（皆为派生值 ⇒ 不落库）；
- 两列均 ``nullable=True``（存量行无需回填；``NULL`` = 未设置头像 ⇒ 走默认占位）。

``upgrade`` / ``downgrade`` **成对**且互为逆操作。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_user_profile_avatar"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

#: 本次唯一允许新增的列（**顺序冻结**：upgrade 顺序与 downgrade 逆序一一对应）
NEW_COLUMNS = (
    ("avatar_key", sa.String(length=64)),
    ("avatar_updated_at", sa.DateTime()),
)


def upgrade() -> None:
    """新增 ``user_profile.avatar_key`` / ``avatar_updated_at``（均为 NULL 可空）。"""
    op.add_column(
        "user_profile",
        sa.Column("avatar_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("avatar_updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """逆序移除本次新增的 2 列（**恢复到 0001 的 ``user_profile`` 结构**）。"""
    op.drop_column("user_profile", "avatar_updated_at")
    op.drop_column("user_profile", "avatar_key")
