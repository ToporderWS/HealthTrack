# -*- coding: utf-8 -*-
"""``password_reset_token`` —— 一次性密码重置凭证（L2，**B1 新增**）。

依据
----
- ``CR-F006-001``（``F-006`` →「V1.0 发布前补齐功能」，2026-09-23 生效）
- 《S1-A-安全规则冻结清单》「变更登记」``SR-5``：**不得当作 Access Token 使用**
  （不授予任何普通登录权限）；``SR-6``：**短生命周期 + 一次性 + 用后立即失效**；
  ``SR-4``：**不得进入日志**

它与 ``user_session`` 的关系（**刻意完全解耦**）
--------------------------------------------
| | ``user_session`` | ``password_reset_token``（本表） |
|---|---|---|
| 承载物 | Access JWT + Refresh Token | 不透明随机串 |
| 派生权限 | **登录态**（可访问业务接口） | **无**（只够换一次「设置新密码」） |
| 有效期 | 2h / 30d | 15 分钟 |
| 表 | 独立 | **独立**（不复用 ``revoked_reason``，不动 A-05 / A-07 主逻辑） |

**本表不存原始 token**：只存 ``SHA-256(token)`` 十六进制（``CHAR(64)``，与
``user_session.refresh_token_hash`` 同算法同口径）。原始 token 只在
「生成 → 投递 → 用户提交」这条链路上短暂存在，**绝不落库、绝不落日志**。

三种「失效」在结构上互不混淆
--------------------------
| 状态 | 判定 | 写入者 |
|---|---|---|
| 有效 | ``consumed_at IS NULL AND revoked_at IS NULL AND expires_at > now`` | — |
| 已用尽 | ``consumed_at IS NOT NULL`` | 用户完成重置（一次性消费） |
| 被作废 | ``revoked_at IS NOT NULL`` | **密码被成功改变**（改密或找回重置）⇒ 批量作废该账号全部未消费凭证（``E-24``） |

⚠️ 为什么``revoked_at`` 与 ``consumed_at`` **必须分开**（而不是复用一列）：
``E-24`` 的冻结要求是「此前**尚未消费**的凭证必须全部失效」——
若把「作废」也写进 ``consumed_at``，事后审计将**无法区分**
「用户真的用过一次」与「因改密被批量清掉」，也给后续「作废原因 / 计数」留不下扩展位。
（B1 只**建能力**；真正调用批量作废属 **B3**，且 ``A-05`` 主逻辑在 B1 **一行未改**。）
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CHAR, CheckConstraint, DateTime, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BIGINT_UNSIGNED, TABLE_KWARGS, Base

#: 绑定「期限必须晚于签发」—— 结构上排除「永不过期 / 负期限」凭证
EXPIRY_AFTER_CREATED_CHECK = "expires_at > created_at"


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"
    __table_args__ = (
        # 一次性凭证按 token_hash 精确查表（并顺带保证同一凭证不会有两行）
        Index("uk_prt_token_hash", "token_hash", unique=True),
        # 支撑「查该账号当前未消费凭证」与「批量作废（E-24）」的定位于计数
        Index("idx_prt_user_outstanding", "user_id", "consumed_at", "revoked_at"),
        # 支撑过期清理
        Index("idx_prt_expires", "expires_at"),
        CheckConstraint(EXPIRY_AFTER_CREATED_CHECK, name="ck_prt_expiry_after_created"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    #: ``SHA-256(token)`` 十六进制；**绝无原始 token**
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: 非空 = 已被用户消费过一次（一次性；不可重放）
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: 非空 = 因**密码成功改变**被批量作废（``E-24``）；与 ``consumed_at`` 语义互斥可辨
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
