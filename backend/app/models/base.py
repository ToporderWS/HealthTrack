# -*- coding: utf-8 -*-
"""ORM 声明式基类与公共类型。

依据：《S1-B 数据库设计文档》v1.2（**8 张表 / 17 个索引**，SEALED）

通用约定（S1-B §六 通用约定）：
- 所有表 ``ENGINE=InnoDB``、``DEFAULT CHARSET=utf8mb4``、``COLLATE=utf8mb4_0900_ai_ci``
- ``created_at`` / ``updated_at`` **由服务端写入**，不使用数据库 ``DEFAULT CURRENT_TIMESTAMP``
  （与 D-4「本地墙上时间直存」一致）
- **不使用外键（FOREIGN KEY）**（S1-B §9.3 明确 V1.0 不采用）
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Integer, SmallInteger
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


# ── 无符号整型（MySQL 目标类型；with_variant 保证其他方言下仍可用）──
BIGINT_UNSIGNED = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
TINYINT_UNSIGNED = SmallInteger().with_variant(mysql.TINYINT(unsigned=True), "mysql")
INT_UNSIGNED = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

#: 统一的表选项（InnoDB / utf8mb4 / utf8mb4_0900_ai_ci）
TABLE_KWARGS: dict = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}

#: 软删字段组的系统一致性 CHECK（S1-B §6.1 / §9.3「✅（可选）」）
#: 仅约束系统自身写入逻辑，**不会拒绝任何用户输入**
SOFT_DELETE_CHECK = "is_deleted = 0 OR deleted_at IS NOT NULL"
