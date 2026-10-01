# -*- coding: utf-8 -*-
"""Alembic 迁移环境。

设计要点：
1. **连接串不写入 ``alembic.ini``**，而是从应用配置（``.env*``）动态注入，
   避免真实凭据进入仓库（S1-D §5.1）。
2. ``target_metadata`` = 应用 ORM 模型的 ``Base.metadata``，保证
   **代码模型 ↔ Alembic 迁移 ↔ 实际数据库** 三者一致。
3. 迁移脚本本批为**手写初始迁移**（严格对应 S1-B 的 8 张表 + 17 个索引）。
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 使 ``import app`` 可用（backend/ 加入 sys.path）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.core.config import load_config  # noqa: E402
from app.models import Base  # noqa: E402
from app import models as _models  # noqa: E402,F401  确保 8 张表全部注册

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从应用配置注入连接串（``%`` 需转义，避免 configparser 插值报错）
_app_cfg = load_config()
config.set_main_option(
    "sqlalchemy.url", str(_app_cfg["SQLALCHEMY_DATABASE_URI"]).replace("%", "%%")
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅根据 URL 生成 SQL，不建立连接。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：建立连接并执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
