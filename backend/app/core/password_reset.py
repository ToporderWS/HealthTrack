# -*- coding: utf-8 -*-
"""找回密码 —— 邮箱规范化 / 验证码 HMAC / 一次性重置凭证（**B1 数据层与安全基础**）。

依据（本次范围变更正本）
------------------------
- ``CR-F006-001-需求变更记录.md``（``F-006``：P1/V1.1 不做 → **V1.0 发布前补齐功能**）
- 《S1-A-安全规则冻结清单》文末「变更登记（``CR-F006-001`` · 2026-09-23）」``SR-1``~``SR-13``
- 《S1-B 数据库设计文档》§6.2 / §9.3（``utf8mb4`` / 本地墙上时间 / **0 外键**）

本模块**只提供密码学与规范化原语**，不含任何 HTTP、编排、发信或日志调用：

- 验证码明文 **永不出本模块**：调用方取得 ``code`` 后只负责投递，**绝不落库、绝不落日志**；
  落库的只有 ``HMAC-SHA256(pepper, f"{user_id}:{purpose}:{code}")``。
- 重置凭证落库的只有 ``SHA-256(token)``（与 ``user_session.refresh_token_hash`` 同口径同算法）。

关键设计裁定（与 ``SR-*`` 逐条对应）
----------------------------------
| 项 | 裁定 | 依据 / 理由 |
|---|---|---|
| pepper 来源 | **独立环境变量 ``PASSWORD_RESET_PEPPER``** | 不复用 ``SECRET_KEY`` ⇒ 用途分离 + 可独立轮换 |
| 验证码哈希 | ``HMAC-SHA256``，消息体 ``user_id:purpose:code`` | **拒裸 SHA-256**（6 位码可离线全枚举）；**拒 bcrypt**（无需慢哈希，且会拖垮校验路径） |
| ``purpose`` 绑定 | **必须进 HMAC 消息体** | 防「同一 code 跨用途复用」（``email_bind`` 的码不得通过 ``password_reset`` 校验） |
| ``user_id`` 绑定 | **必须进 HMAC 消息体** | 防「A 的码在 B 的账号上通过」（即使两人拿到同一个 6 位数字） |
| 比对方式 | ``hmac.compare_digest`` | 常数时间，避免时序侧信道 |
| 重置凭证 | ``secrets.token_urlsafe(48)``（384 bit CSPRNG） | ≥ ``S1-D`` 的 256 bit 要求；与 ``refresh_token`` 同口径 |
| 凭证哈希 | **裸 ``SHA-256``**（不加 pepper） | 384 bit 随机值**不可枚举** ⇒ 无需 pepper；与 ``refresh_token_hash`` 保持同一算法便于审计 |
| 邮箱规范化 | **仅** ``strip`` + ``lower`` | 见 :func:`normalize_email`：**禁止**去点 / 去 ``+tag`` 等特例归一化 |

⚠️ 本模块**不含**任何「发送 / 配置 SMTP」能力（B1 明令禁止）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Optional

# ══════════════════════════════════════════════════════════════════
# 策略常量（**单一来源**：B2/B3 一律引用此处，不得各写一份）
# ══════════════════════════════════════════════════════════════════

#: 验证码位数（6 位十进制；``SR-12``）
CODE_LENGTH = 6
#: 验证码有效期（分钟）。随挑战记录 ``expires_at`` 落库，**服务端判定，不信任客户端**
CODE_TTL_MINUTES = 15
#: 单条验证码允许的最大**校验失败**次数（``SR-12`` 尝试次数限制；超限即作废该码）
CODE_MAX_ATTEMPTS = 5
#: 同一账号 + 同一 ``purpose`` 同时允许存在的**有效**验证码条数（``SR-6`` 一次性口径）
#: = 1 ⇒ **签发新码即使旧码失效**（不给攻击者「多码并存」的并行机会）
CODE_MAX_ACTIVE_PER_PURPOSE = 1
#: 重发冷却（秒）。B0 冻结：`[重发] 60s 倒计时（冷却期内 disabled）`
RESEND_COOLDOWN_SECONDS = 60
#: 一次性重置凭证有效期（分钟）。**短生命周期**（``SR-6``）
RESET_TOKEN_TTL_MINUTES = 15
#: 一次性重置凭证随机熵：48 字节 = 384 bit（``SR-6`` 密码学安全随机）
RESET_TOKEN_BYTES = 48
#: 凭证哈希列长度（``CHAR(64)`` = SHA-256 十六进制摘要）
HASH_HEX_LEN = 64

#: ``verification_code.purpose`` 取值枚举（**冻结**：防跨用途复用）
PURPOSE_PASSWORD_RESET = "password_reset"
#: 预留：邮箱绑定验证（B4 邮箱绑定入口使用；B1 **不启用**，仅注册常量）
PURPOSE_EMAIL_BIND = "email_bind"
ALLOWED_PURPOSES = (PURPOSE_PASSWORD_RESET, PURPOSE_EMAIL_BIND)

#: 邮箱长度上限（RFC 5321 路径上限 254 字符）
EMAIL_MAX_LEN = 254
#: 邮箱 local-part 上限（RFC 5321 §4.5.3.1.1）
EMAIL_LOCAL_MAX_LEN = 64
#: 邮箱格式校验（**保守字符集**；用于规范化后的最终确认，不作为唯一防线）
EMAIL_RE = re.compile(
    r"^[^@\s]{1,%d}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$" % EMAIL_LOCAL_MAX_LEN
)
#: 「占位符」判定（与 ``core.config._is_placeholder`` 同口径）
_PLACEHOLDER_MARK = "CHANGE_ME"


# ══════════════════════════════════════════════════════════════════
# 邮箱规范化（canonical storage）
# ══════════════════════════════════════════════════════════════════
def normalize_email(raw) -> str:
    """邮箱规范化 —— **只做两件事**：去首尾空白 + 转小写。

    这是本项目的 **canonical storage** 口径：``user_account.email`` 只存本函数输出，
    ``uk_user_account_email`` 唯一索引即建立在规范形之上。

    ⚠️ **刻意不做**以下「常见归一化」（会引入比它解决的问题更大的风险）：

    - 不去掉 local-part 中的 ``.``（``a.b@gmail.com`` 与 ``ab@gmail.com`` 在 Gmail
      下等价，但在**本项目并不等价**）；
    - 不去掉 ``+tag``（``me+1@x.com`` / ``me+2@x.com`` 是**两个不同的可投递地址**）；
    - 不做 IDN / punycode 转换，不做 Unicode 折叠（NFKC）。

    理由：以上任一操作都会把**两个不同人类用户**的地址折叠成同一规范形 ⇒
    唯一约束把「B 的邮箱」判为「A 已占用」，或更糟——把找回请求投递到错误的账号语义上。
    **规范化只允许做「不改变地址身份」的变换**（大小写与外围空白即属此类）。

    大小写之所以安全：域名大小写不敏感（RFC 4343），local-part 虽在 RFC 5321 中
    理论上大小写敏感，但**所有主流 MTA 实际按不敏感处理**，且本项目邮箱用途为
    「账号找回凭据」，**必须**按不敏感处理以免用户因大小写差异被拒。
    """
    return "" if raw is None else str(raw).strip().lower()


def is_valid_email(normalized: str) -> bool:
    """格式校验（**入参须已过 :func:`normalize_email`**）。"""
    value = str(normalized or "")
    if not value or len(value) > EMAIL_MAX_LEN:
        return False
    return EMAIL_RE.match(value) is not None


# ══════════════════════════════════════════════════════════════════
# pepper 装载（fail-fast，绝不落回默认值）
# ══════════════════════════════════════════════════════════════════
def is_usable_pepper(value) -> bool:
    """pepper 是否可用（非空且不是占位符）。"""
    text = "" if value is None else str(value).strip()
    return bool(text) and _PLACEHOLDER_MARK not in text.upper()


def require_pepper(value) -> str:
    """取 pepper；缺失 / 占位符 ⇒ ``RuntimeError``（**绝不静默降级**）。"""
    if not is_usable_pepper(value):
        raise RuntimeError(
            "PASSWORD_RESET_PEPPER 未配置：找回密码验证码 HMAC 的 pepper "
            "必须来自环境变量（backend/.env），不得使用默认值或占位符"
        )
    return str(value).strip()


def require_purpose(value) -> str:
    """取 ``purpose``；非法值 ⇒ ``ValueError``（**防跨用途复用**）。"""
    text = "" if value is None else str(value).strip()
    if text not in ALLOWED_PURPOSES:
        raise ValueError(
            "verification purpose 非法：%r（可选 %s）"
            % (text, " / ".join(ALLOWED_PURPOSES))
        )
    return text


# ══════════════════════════════════════════════════════════════════
# 验证码（**明文绝不落库、绝不落日志**）
# ══════════════════════════════════════════════════════════════════
def generate_verification_code() -> str:
    """生成 6 位十进制验证码（**均匀分布**，用 ``secrets`` 而非 ``random``）。"""
    upper = 10 ** CODE_LENGTH
    return str(secrets.randbelow(upper)).zfill(CODE_LENGTH)


def code_hmac_message(user_id: int, purpose: str, code: str) -> bytes:
    """HMAC 消息体 ``"{user_id}:{purpose}:{code}"``（UTF-8）。

    冻结形态 —— **三段用 ``:`` 连接，顺序固定**：
    ``user_id`` 与 ``purpose`` 一起构成「这条码只对 这个账号 + 这个用途 有效」的绑定。
    """
    return ("%d:%s:%s" % (int(user_id), str(purpose), str(code))).encode("utf-8")


def hash_verification_code(pepper, user_id: int, purpose: str, code: str) -> str:
    """``HMAC-SHA256(pepper, "user_id:purpose:code")`` → 64 位十六进制小写。

    **落库值只允许是本函数输出**（``verification_code.code_hash CHAR(64)``）。
    明文 ``code`` 仅存在于调用栈内。
    """
    key = require_pepper(pepper)
    p = require_purpose(purpose)
    msg = code_hmac_message(user_id, p, code)
    return hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_verification_code(
    pepper, user_id: int, purpose: str, code: str, expected_hash: Optional[str]
) -> bool:
    """常数时间比对；任何异常一律 ``False``（不泄露内部细节）。"""
    if not code or not expected_hash:
        return False
    try:
        actual = hash_verification_code(pepper, user_id, purpose, code)
    except (RuntimeError, ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, str(expected_hash).strip().lower())


# ══════════════════════════════════════════════════════════════════
# 一次性重置凭证（**原始 token 绝不落库、绝不落日志**）
# ══════════════════════════════════════════════════════════════════
def generate_reset_token() -> str:
    """生成不透明一次性重置凭证（CSPRNG，384 bit）。

    **不是** Access Token、**不是** Refresh Token（``SR-5``）：本值不携带任何
    ``sub`` / ``exp`` / 签名，**不可**用于访问任何业务接口，只在
    ``password_reset_token.token_hash`` 处做一次「查表 + 判定」。
    """
    return secrets.token_urlsafe(RESET_TOKEN_BYTES)


def hash_reset_token(raw: str) -> str:
    """``SHA-256`` 十六进制摘要（DB **只存该摘要**）。

    不加 pepper：原始 token 为 384 bit 随机值 ⇒ 不存在离线枚举空间，
    加 pepper 只增加轮换时的运维负担而无实质收益；与既有
    ``core.security.hash_refresh_token`` **同算法同口径**，便于统一审计。
    """
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


__all__ = [
    "CODE_LENGTH",
    "CODE_TTL_MINUTES",
    "CODE_MAX_ATTEMPTS",
    "CODE_MAX_ACTIVE_PER_PURPOSE",
    "RESEND_COOLDOWN_SECONDS",
    "RESET_TOKEN_TTL_MINUTES",
    "RESET_TOKEN_BYTES",
    "HASH_HEX_LEN",
    "PURPOSE_PASSWORD_RESET",
    "PURPOSE_EMAIL_BIND",
    "ALLOWED_PURPOSES",
    "EMAIL_MAX_LEN",
    "normalize_email",
    "is_valid_email",
    "is_usable_pepper",
    "require_pepper",
    "require_purpose",
    "generate_verification_code",
    "code_hmac_message",
    "hash_verification_code",
    "verify_verification_code",
    "generate_reset_token",
    "hash_reset_token",
]
