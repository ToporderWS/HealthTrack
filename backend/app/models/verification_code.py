# -*- coding: utf-8 -*-
"""``verification_code`` —— 邮箱验证码挑战（L2，**B1 新增**）。

依据
----
- ``CR-F006-001``（``F-006`` →「V1.0 发布前补齐功能」，2026-09-23 生效）
- 《S1-A-安全规则冻结清单》「变更登记」``SR-1``~``SR-4``（**不得明文入库 / 不得进日志**）、
  ``SR-12``（频率限制 / 尝试次数限制 / 重发冷却）
- 设计口径来源：``core/password_reset.py``（**策略常量的唯一来源**，本表不重复定义）

核心约束（**结构上保证，而非靠调用方自觉**）
------------------------------------------
1. 本表**没有**任何可存放验证码明文的列：只有 ``code_hash``（``CHAR(64)``）。
   落库值**只允许**是 ``HMAC-SHA256(pepper, f"{user_id}:{purpose}:{code}")``。
   为什么不是裸 ``SHA-256``：6 位十进制验证码只有 10^6 种 ⇒ 裸哈希可**离线全枚举**；
   为什么不是 ``bcrypt``：验证码生命周期只有分钟级、且必须防枚举爆破，
   慢哈希只会拖垮高频校验路径，真正的防线是 pepper + 尝试次数限制。
2. ``purpose`` 必须参与 HMAC 消息体 ⇒ 同一串数字在 ``email_bind`` 与
   ``password_reset`` 之间**互不通用**（防跨用途复用）。
3. ``expires_at`` 由服务端写入并判定，**不信任客户端任何时间输入**。

冻结的时效与状态语义
-------------------
| 项 | 冻结值 / 语义 | 常量 |
|---|---|---|
| TTL | 15 分钟 | ``CODE_TTL_MINUTES`` |
| 最大校验失败次数 | 5 次（超限即作废该码） | ``CODE_MAX_ATTEMPTS`` |
| 同账号同 ``purpose`` 同时有效条数 | **1**（签发新码 ⇒ 旧码立即失效） | ``CODE_MAX_ACTIVE_PER_PURPOSE`` |
| 重发冷却 | 60 秒 | ``RESEND_COOLDOWN_SECONDS`` |
| ``consumed_at`` | **非空 = 已消费且不可再用**（无论成功消费还是被新码作废均写此列） | — |
| 「有效」判定 | ``consumed_at IS NULL AND expires_at > now`` | — |
| ``attempt_count`` | 校验**失败**次数累加（成功不累加）；达上限即置 ``consumed_at`` | — |

**刻意的「不落库」清单**（`B0 §四` 要求「不为了看起来专业堆无用字段」）
------------------------------------------------------------------
- **不落 ``request_ip`` / ``user_agent``**：① 增加一类个人信息 ⇒ 隐私政策披露面扩大，
  与「最小必要」冲突；② B1 的限流与冷却由「账号 + 时间窗」即可表达，
  IP 维度若日后确需，应在 **B2 运行时内存/中间层**做，不进账号库；
- **不落验证码明文**（无此列）；
- **不落发信结果正文**（SMTP 响应可能含收件人地址，属个人信息）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CHAR, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BIGINT_UNSIGNED, TABLE_KWARGS, TINYINT_UNSIGNED, Base

#: 绑定「期限必须晚于签发」—— 结构上排除「永不过期 / 负期限」挑战
EXPIRY_AFTER_CREATED_CHECK = "expires_at > created_at"


class VerificationCode(Base):
    __tablename__ = "verification_code"
    __table_args__ = (
        # 支撑「取该账号该用途当前有效码」与「批量作废」两类查询
        Index("idx_vcode_user_purpose", "user_id", "purpose", "consumed_at"),
        # 支撑过期清理（与 user_session 的 *_exp 索引同一口径）
        Index("idx_vcode_expires", "expires_at"),
        CheckConstraint(EXPIRY_AFTER_CREATED_CHECK, name="ck_vcode_expiry_after_created"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_UNSIGNED, nullable=False)
    #: ``password_reset`` / ``email_bind``（见 ``core.password_reset.ALLOWED_PURPOSES``）
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    #: ``HMAC-SHA256(pepper, "user_id:purpose:code")`` 十六进制；**绝无明文**
    code_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: 非空 = 已消费 / 已作废，**不可再用**
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: 校验**失败**次数（成功后不累加）；服务端递增，达上限即作废
    attempt_count: Mapped[int] = mapped_column(
        TINYINT_UNSIGNED, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
