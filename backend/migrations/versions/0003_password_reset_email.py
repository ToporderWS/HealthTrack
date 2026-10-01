# -*- coding: utf-8 -*-
"""找回密码数据层：``user_account`` 新增邮箱字段 ＋ 2 张新表

Revision ID: 0003_password_reset_email
Revises: 0002_user_profile_avatar
Create Date: 2026-09-23

严格依据：

- ``CR-F006-001-需求变更记录.md``（``F-006``：P1/V1.1 不做 → **V1.0 发布前补齐功能**）
- 《S1-A-安全规则冻结清单》文末「变更登记（``CR-F006-001`` · 2026-09-23）」``SR-1``~``SR-13``
- 需求方 2026-09-23 B1 授权（**安全基础设施 + DB/Migration 设计与实现批**）

UP（**只增不改、向后兼容存量账号**）
--------------------------------
1. ``user_account`` ＋2 列：``email VARCHAR(254) NULL COLLATE utf8mb4_0900_as_ci`` /
   ``email_verified_at DATETIME NULL``（**均 NULL 可空 ⇒ 存量 6 账号无需回填**）
2. ``user_account`` ＋1 唯一索引 ``uk_user_account_email``
   （MySQL 唯一索引**对 NULL 不去重**，多个 ``email=NULL`` 可共存 —— 已实测）
3. ``user_account`` ＋1 CHECK ``ck_user_account_email_pair``
   （``email`` 与 ``email_verified_at`` **同时为空 / 同时非空**）
4. 新建 ``verification_code``（8 列 ＋ 2 索引 ＋ 1 CHECK）
5. 新建 ``password_reset_token``（7 列 ＋ 3 索引 ＋ 1 CHECK）

**禁止任何其它 schema 漂移**：0 列改名、0 列删除、0 类型变更、0 外键、
**0 数据回填**、**0 默认值**（不存在「给老账号自动生成邮箱」这类动作）。

DOWN
----
按逆序回退到 ``0002_user_profile_avatar``：删 2 张表 → 删 CHECK → 删唯一索引 →
删 2 列。因两列均为新增且**全部为 NULL**，下降级**不丢失任何既有业务数据**
（四段往返 ``0002 → 0003 → 0002 → 0003`` 已实测全量对拍，见
``scripts/verify_b1_migration.py``）。

⚠️ 本迁移**不触碰** ``A-05`` / ``A-07`` 逻辑，**不新增** ``revoked_reason`` 取值，
**不修改** ``login_failure_state`` / ``user_session`` 等既有表（那三项均须单独授权）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "0003_password_reset_email"
down_revision = "0002_user_profile_avatar"
branch_labels = None
depends_on = None

TABLE_KW = dict(
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

#: 邮箱长度上限（RFC 5321）与列级排序规则（大小写不敏感 + 重音敏感）
EMAIL_MAX_LEN = 254
EMAIL_COLLATION = "utf8mb4_0900_as_ci"

#: ``email`` / ``email_verified_at`` 的「同时为空 / 同时非空」不变量
EMAIL_PAIR_CHECK = (
    "(email IS NULL AND email_verified_at IS NULL) "
    "OR (email IS NOT NULL AND email_verified_at IS NOT NULL)"
)
#: 凭证「期限晚于签发」不变量（结构上排除永不过期 / 负期限）
EXPIRY_AFTER_CREATED_CHECK = "expires_at > created_at"

#: 本次新增的「表 → 索引」清单（供人工核对，**不作为任何判据的期望值来源**）
NEW_INDEXES = {
    "user_account": ("uk_user_account_email",),
    "verification_code": ("idx_vcode_user_purpose", "idx_vcode_expires"),
    "password_reset_token": (
        "uk_prt_token_hash",
        "idx_prt_user_outstanding",
        "idx_prt_expires",
    ),
}


def upgrade() -> None:
    """新增邮箱字段与找回密码 2 张表（0002 → 0003）。"""

    # ── 1-2. user_account 新增 2 列（NULL 可空，无 server_default）──────
    op.add_column(
        "user_account",
        sa.Column(
            "email",
            sa.String(length=EMAIL_MAX_LEN, collation=EMAIL_COLLATION),
            nullable=True,
        ),
    )
    op.add_column(
        "user_account",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )

    # ── 3. 唯一索引（canonical = 规范化后的低形邮箱）────────────────────
    op.create_index("uk_user_account_email", "user_account", ["email"], unique=True)

    # ── 4. 「同时为空 / 同时非空」DB 级不变量 ────────────────────────────
    op.create_check_constraint(
        "ck_user_account_email_pair", "user_account", EMAIL_PAIR_CHECK
    )

    # ── 5. verification_code ────────────────────────────────────────────
    op.create_table(
        "verification_code",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("code_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "attempt_count",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(EXPIRY_AFTER_CREATED_CHECK, name="ck_vcode_expiry_after_created"),
        comment="邮箱验证码挑战（只存 HMAC 哈希）",
        **TABLE_KW,
    )
    op.create_index(
        "idx_vcode_user_purpose",
        "verification_code",
        ["user_id", "purpose", "consumed_at"],
        unique=False,
    )
    op.create_index("idx_vcode_expires", "verification_code", ["expires_at"], unique=False)

    # ── 6. password_reset_token ─────────────────────────────────────────
    op.create_table(
        "password_reset_token",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(EXPIRY_AFTER_CREATED_CHECK, name="ck_prt_expiry_after_created"),
        comment="一次性密码重置凭证（只存 SHA-256）",
        **TABLE_KW,
    )
    op.create_index(
        "uk_prt_token_hash", "password_reset_token", ["token_hash"], unique=True
    )
    op.create_index(
        "idx_prt_user_outstanding",
        "password_reset_token",
        ["user_id", "consumed_at", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "idx_prt_expires", "password_reset_token", ["expires_at"], unique=False
    )


def downgrade() -> None:
    """逆序回退到 0002（删表 → 删约束 → 删索引 → 删列）。"""

    # ── 表（逆序）───────────────────────────────────────────────────────
    for idx in ("idx_prt_expires", "idx_prt_user_outstanding", "uk_prt_token_hash"):
        op.drop_index(idx, table_name="password_reset_token")
    op.drop_table("password_reset_token")

    for idx in ("idx_vcode_expires", "idx_vcode_user_purpose"):
        op.drop_index(idx, table_name="verification_code")
    op.drop_table("verification_code")

    # ── user_account 的约束 / 索引 / 列（逆序）──────────────────────────
    op.drop_constraint("ck_user_account_email_pair", "user_account", type_="check")
    op.drop_index("uk_user_account_email", table_name="user_account")
    op.drop_column("user_account", "email_verified_at")
    op.drop_column("user_account", "email")
