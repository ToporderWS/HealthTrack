# -*- coding: utf-8 -*-
"""初始迁移：8 张表 + 17 个索引

Revision ID: 0001_initial_schema
Revises: （无）
Create Date: 2026-09-13

严格依据：《S1-B 数据库设计文档》v1.2（SEALED）
- 表：user_account / user_profile / health_record / record_tag / health_goal /
        user_session / login_failure_state / export_job（**共 8 张**，提醒表 0 张）
- 索引：**17 个（7 唯一 + 10 普通）**
- 通用：ENGINE=InnoDB、CHARSET=utf8mb4、COLLATE=utf8mb4_0900_ai_ci
- **不使用外键（FOREIGN KEY）**；**不添加任何 S1-B 之外的字段 / 表 / 索引**
- 派生值不落库；`user_profile` **不含 target_weight**（D-1：唯一源 = health_goal）
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

TABLE_KW = dict(
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_0900_ai_ci",
)

SOFT_DELETE_CHECK = "is_deleted = 0 OR deleted_at IS NOT NULL"


def upgrade() -> None:
    """建立 V1.0 全部 8 张表与 17 个索引。"""

    # ── 1. user_account ────────────────────────────────────────────────
    op.create_table(
        "user_account",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.String(length=100), nullable=False),
        sa.Column(
            "password_algo",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'bcrypt'"),
        ),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default=sa.text("'user'")
        ),
        sa.Column("terms_agreed_at", sa.DateTime(), nullable=True),
        sa.Column("agreement_version", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="用户账号",
        **TABLE_KW,
    )
    op.create_index(
        "uk_user_account_username", "user_account", ["username"], unique=True
    )

    # ── 2. user_profile ────────────────────────────────────────────────
    op.create_table(
        "user_profile",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("nickname", sa.String(length=20), nullable=True),
        sa.Column("gender", mysql.TINYINT(unsigned=True), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("height_cm", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("initial_weight_kg", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("blood_type", sa.String(length=4), nullable=True),
        sa.Column("medical_history", sa.Text(), nullable=True),
        sa.Column("allergy_history", sa.Text(), nullable=True),
        sa.Column("medication_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="健康档案",
        **TABLE_KW,
    )
    op.create_index("uk_user_profile_user", "user_profile", ["user_id"], unique=True)

    # ── 3. health_record ───────────────────────────────────────────────
    op.create_table(
        "health_record",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("metric_type", sa.String(length=16), nullable=False),
        sa.Column("value_1", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("value_2", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("value_3", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("unit", sa.String(length=12), nullable=False),
        sa.Column("attr_1", sa.String(length=24), nullable=True),
        sa.Column("attr_2", sa.String(length=24), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("time_start", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "is_deleted",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(SOFT_DELETE_CHECK, name="ck_health_record_soft_delete"),
        comment="健康记录（8 类指标单表）",
        **TABLE_KW,
    )
    op.create_index(
        "idx_hr_user_metric_time",
        "health_record",
        ["user_id", "metric_type", sa.text("recorded_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_hr_user_time",
        "health_record",
        ["user_id", sa.text("recorded_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_hr_cleanup", "health_record", ["is_deleted", "deleted_at"], unique=False
    )

    # ── 4. record_tag ──────────────────────────────────────────────────
    op.create_table(
        "record_tag",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("record_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("tag_value", sa.String(length=16), nullable=False),
        sa.Column(
            "is_deleted",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(SOFT_DELETE_CHECK, name="ck_record_tag_soft_delete"),
        comment="记录标签（多值属性）",
        **TABLE_KW,
    )
    op.create_index(
        "uk_record_tag", "record_tag", ["record_id", "tag_value"], unique=True
    )
    op.create_index("idx_tag_user", "record_tag", ["user_id", "record_id"], unique=False)

    # ── 5. health_goal ─────────────────────────────────────────────────
    op.create_table(
        "health_goal",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("goal_type", sa.String(length=16), nullable=False),
        sa.Column("period_type", sa.String(length=8), nullable=False),
        sa.Column("target_value", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("unit", sa.String(length=12), nullable=False),
        sa.Column("attr_1", sa.String(length=16), nullable=True),
        sa.Column("start_weight_kg", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_deleted",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "deleted_marker",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(SOFT_DELETE_CHECK, name="ck_health_goal_soft_delete"),
        comment="健康目标",
        **TABLE_KW,
    )
    op.create_index(
        "uk_goal_user_type_active",
        "health_goal",
        ["user_id", "goal_type", "deleted_marker"],
        unique=True,
    )

    # ── 6. user_session ────────────────────────────────────────────────
    op.create_table(
        "user_session",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("refresh_token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("access_token_id", sa.CHAR(length=64), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(length=24), nullable=True),
        sa.Column(
            "export_pwd_fail_count",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "change_pwd_fail_count",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="用户会话 / Token 状态",
        **TABLE_KW,
    )
    op.create_index(
        "uk_session_refresh", "user_session", ["refresh_token_hash"], unique=True
    )
    op.create_index(
        "idx_session_user", "user_session", ["user_id", "revoked_at"], unique=False
    )
    op.create_index(
        "idx_session_access", "user_session", ["access_token_id"], unique=False
    )
    op.create_index(
        "idx_session_refresh_exp", "user_session", ["refresh_expires_at"], unique=False
    )

    # ── 7. login_failure_state ─────────────────────────────────────────
    op.create_table(
        "login_failure_state",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=20), nullable=False),
        sa.Column(
            "fail_count",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("first_fail_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column(
            "lock_level",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="登录失败与锁定状态",
        **TABLE_KW,
    )
    op.create_index(
        "uk_login_fail_username", "login_failure_state", ["username"], unique=True
    )
    op.create_index(
        "idx_login_fail_locked", "login_failure_state", ["locked_until"], unique=False
    )

    # ── 8. export_job ──────────────────────────────────────────────────
    op.create_table(
        "export_job",
        sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("metric_types", sa.String(length=128), nullable=True),
        sa.Column("range_start", sa.DateTime(), nullable=True),
        sa.Column("range_end", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("file_token", sa.CHAR(length=32), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("record_count", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("download_expires_at", sa.DateTime(), nullable=False),
        sa.Column("purge_at", sa.DateTime(), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="数据导出任务与临时文件",
        **TABLE_KW,
    )
    op.create_index("uk_export_token", "export_job", ["file_token"], unique=True)
    op.create_index(
        "idx_export_user", "export_job", ["user_id", sa.text("created_at DESC")], unique=False
    )
    op.create_index(
        "idx_export_purge", "export_job", ["purge_at", "status"], unique=False
    )


def downgrade() -> None:
    """按逆序删除全部索引与表。"""

    # 索引（逆序）
    op.drop_index("idx_export_purge", table_name="export_job")
    op.drop_index("idx_export_user", table_name="export_job")
    op.drop_index("uk_export_token", table_name="export_job")
    op.drop_index("idx_login_fail_locked", table_name="login_failure_state")
    op.drop_index("uk_login_fail_username", table_name="login_failure_state")
    op.drop_index("idx_session_refresh_exp", table_name="user_session")
    op.drop_index("idx_session_access", table_name="user_session")
    op.drop_index("idx_session_user", table_name="user_session")
    op.drop_index("uk_session_refresh", table_name="user_session")
    op.drop_index("uk_goal_user_type_active", table_name="health_goal")
    op.drop_index("idx_tag_user", table_name="record_tag")
    op.drop_index("uk_record_tag", table_name="record_tag")
    op.drop_index("idx_hr_cleanup", table_name="health_record")
    op.drop_index("idx_hr_user_time", table_name="health_record")
    op.drop_index("idx_hr_user_metric_time", table_name="health_record")
    op.drop_index("uk_user_profile_user", table_name="user_profile")
    op.drop_index("uk_user_account_username", table_name="user_account")

    # 表（逆序）
    op.drop_table("export_job")
    op.drop_table("login_failure_state")
    op.drop_table("user_session")
    op.drop_table("health_goal")
    op.drop_table("record_tag")
    op.drop_table("health_record")
    op.drop_table("user_profile")
    op.drop_table("user_account")
