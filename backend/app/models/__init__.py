# -*- coding: utf-8 -*-
"""ORM 模型包（V1.0 共 **10 张表**，与 S1-B 封板设计 ＋ ``CR-F006-001`` 变更逐一对应）。

| # | 模型 | 表名 | 索引数 | 备注 |
|---|---|---|---|---|
| 1 | ``UserAccount`` | ``user_account`` | 2 唯一 | 不软删；**0003 新增** ``email`` / ``email_verified_at`` |
| 2 | ``UserProfile`` | ``user_profile`` | 1 唯一 | **无软删字段**；**不含 target_weight**（D-1） |
| 3 | ``HealthRecord`` | ``health_record`` | 3 普通 | 单表 + metric_type |
| 4 | ``RecordTag`` | ``record_tag`` | 1 唯一 + 1 普通 | 无 updated_at |
| 5 | ``HealthGoal`` | ``health_goal`` | 1 唯一 | **唯一使用 deleted_marker** |
| 6 | ``UserSession`` | ``user_session`` | 1 唯一 + 3 普通 | 只存 Token 哈希 |
| 7 | ``LoginFailureState`` | ``login_failure_state`` | 1 唯一 + 1 普通 | 无 created_at |
| 8 | ``ExportJob`` | ``export_job`` | 1 唯一 + 2 普通 | 不返回 file_path |
| 9 | ``VerificationCode`` | ``verification_code`` | 2 普通 | **B1 新增**；只存 HMAC 哈希，**无明文列** |
| 10 | ``PasswordResetToken`` | ``password_reset_token`` | 1 唯一 + 2 普通 | **B1 新增**；只存 SHA-256，**无明文列** |

**合计 23 个索引（9 唯一 + 14 普通）**（``0001`` 的 17 个 ＋ ``0003`` 新增 6 个）；
**提醒相关表 0 张**。
**不使用外键（FOREIGN KEY）**（S1-B §9.3）—— ``0003`` 新增的 2 张表**沿用 0 外键**：
新表同样以 ``user_id`` 逻辑关联 ＋ 索引承担定位能力，理由见 B1 报告
（① 与既有 8 表一致；② ``A-07`` 注销为**单事务显式顺序删除**，外键会引入
与「A-07 只做最小必要扩展」相冲突的级联语义；③ 服务层已承担完整性核查）。
"""
from __future__ import annotations

from app.models.base import Base
from app.models.export_job import ExportJob
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode

__all__ = [
    "Base",
    "UserAccount",
    "UserProfile",
    "HealthRecord",
    "RecordTag",
    "HealthGoal",
    "UserSession",
    "LoginFailureState",
    "ExportJob",
    "VerificationCode",
    "PasswordResetToken",
]

#: V1.0 全部表名（前 8 项顺序与 S1-B §5.1 清单一致；后 2 项为 0003 新增）
ALL_TABLES = (
    "user_account",
    "user_profile",
    "health_record",
    "record_tag",
    "health_goal",
    "user_session",
    "login_failure_state",
    "export_job",
    "verification_code",
    "password_reset_token",
)
