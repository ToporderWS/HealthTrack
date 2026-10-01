# -*- coding: utf-8 -*-
"""认证安全原语：密码哈希 / 密码与用户名规则 / Access JWT / Refresh Token。

依据（**全部为已封板冻结值，不得自行调整**）：
- 《S1-A 安全规则冻结清单》§1 密码强度、§2 登录失败锁定、§8 会话 Token 有效期
- 《S1-B 第二批 API 接口设计文档》§五 A-01 ~ A-06
- 《S1-D 技术方案最终冻结》§6.1 Token 与 Session / §6.2 密码与登录失败

冻结口径摘要：
- 密码：**bcrypt，cost = 12**；**永不存明文**、**永不入日志**、**永不返回**
- Access Token：**JWT HS256**，含 ``sub``(user_id) / ``jti`` / ``iat`` / ``exp``，**有效期 2 小时**
- Refresh Token：**不透明随机串（≥256 bit CSPRNG）**，DB 只存 **SHA-256 哈希**，**有效期 30 天**
- 签名密钥：``SECRET_KEY``，**只来自环境变量（.env，gitignore）**，本模块**不持有任何默认密钥**

⚠️ 时间口径（D-4 冻结）：
- **数据库字段**一律写「本地墙上时间」（naive ``DATETIME``，秒级），比较也用本地时间；
- **JWT 的 ``iat`` / ``exp``** 是协议级绝对时间戳，**必须用真实 UTC** 计算，
  否则会因为本地时区偏移导致有效期被拉长/缩短。
两者分别由 :func:`now_local` 与 :func:`_utc_now` 承担。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt
import jwt

from app.core.errors import ApiError, ErrorCode

# ── 冻结常量（S1-A §1）────────────────────────────────────────────────
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 64
USERNAME_MIN_LEN = 4
USERNAME_MAX_LEN = 20

#: 用户名：字母开头，仅字母 / 数字 / 下划线（长度另判）
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
#: 至少一个字母 + 至少一个数字
HAS_LETTER_RE = re.compile(r"[A-Za-z]")
HAS_DIGIT_RE = re.compile(r"\d")
WHITESPACE_RE = re.compile(r"\s")

#: Refresh Token 随机字节数：48 字节 = 384 bit（≥ S1-D 要求的 256 bit）
REFRESH_TOKEN_BYTES = 48
#: SHA-256 十六进制长度（对应 ``user_session.refresh_token_hash CHAR(64)``）
REFRESH_HASH_LEN = 64
JWT_ALGORITHM = "HS256"

#: 用于「用户名不存在」时消耗等量 CPU，避免通过响应时间区分账号是否存在。
#: 该值是随机口令的 bcrypt 哈希，**不含任何真实凭据**。
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds=12)).decode("ascii")


# ── 时间 ─────────────────────────────────────────────────────────────
def now_local() -> datetime:
    """本地墙上时间（DB 读写与比较统一口径，秒级）。"""
    return datetime.now().replace(microsecond=0)


def _utc_now() -> datetime:
    """真实 UTC（仅用于 JWT 的 ``iat`` / ``exp`` 绝对时间戳）。"""
    return datetime.now(timezone.utc)


def format_dt(value: Optional[datetime]) -> Optional[str]:
    """``YYYY-MM-DD HH:mm:ss``（D-4：本地墙上时间直存，无时区后缀）。"""
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


# ── 密码 ─────────────────────────────────────────────────────────────
def normalize_password(raw) -> str:
    """密码提交前去除首尾空格（S1-A §1 冻结规则）。"""
    return "" if raw is None else str(raw).strip()


def hash_password(plain: str, rounds: int = 12) -> str:
    """bcrypt 哈希（cost 由配置注入，冻结值 12）。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=int(rounds))).decode("ascii")


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    """哈希比对；任何异常一律返回 False（不泄露内部细节）。"""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), str(hashed).encode("ascii"))
    except (ValueError, TypeError):
        return False


def dummy_verify(plain: str) -> None:
    """对「不存在的用户名」执行一次等价开销的哈希比对（防时序侧信道）。"""
    verify_password(plain, _DUMMY_HASH)


def check_password_rule(raw, username: Optional[str] = None) -> Optional[str]:
    """密码强度校验；返回字段级错误文案，``None`` 表示通过。

    冻结规则（S1-A §1）：8–64 位；**必须同时含字母与数字**；**不得含空格**；
    **不得与用户名相同（不区分大小写）**。
    """
    pwd = normalize_password(raw)
    if len(pwd) < PASSWORD_MIN_LEN:
        return "密码至少 8 位"
    if len(pwd) > PASSWORD_MAX_LEN:
        return "密码最多 64 位"
    if not HAS_LETTER_RE.search(pwd) or not HAS_DIGIT_RE.search(pwd):
        return "密码需同时包含字母和数字"
    if WHITESPACE_RE.search(pwd):
        return "密码不得包含空格"
    if username and pwd.lower() == str(username).strip().lower():
        return "密码不得与用户名相同"
    return None


# ── 用户名 ───────────────────────────────────────────────────────────
def normalize_username(raw) -> str:
    """统一小写存储（S1-B §6.2 冻结：``username`` 一律小写）。"""
    return "" if raw is None else str(raw).strip().lower()


def check_username_rule(raw) -> Optional[str]:
    """用户名格式校验；返回字段级错误文案，``None`` 表示通过。"""
    value = "" if raw is None else str(raw)
    if WHITESPACE_RE.search(value):
        return "用户名不能包含空格"
    if len(value) < USERNAME_MIN_LEN or len(value) > USERNAME_MAX_LEN:
        return "用户名长度需为 4-20 位"
    if not USERNAME_RE.match(value):
        return "用户名需以字母开头，且仅可包含字母、数字或下划线"
    return None


# ── Refresh Token ────────────────────────────────────────────────────
def generate_refresh_token() -> str:
    """生成不透明随机刷新令牌（CSPRNG，≥256 bit）。"""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(raw: str) -> str:
    """SHA-256 十六进制摘要（DB **只存该摘要**，绝不存明文）。"""
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


def generate_access_token_id() -> str:
    """``jti`` / ``access_token_id``（32 位十六进制随机串）。"""
    return secrets.token_hex(16)


# ── Access Token（JWT HS256）──────────────────────────────────────────
def create_access_token(
    user_id: int, jti: str, secret_key: str, access_minutes: int
) -> Tuple[str, datetime]:
    """签发 Access JWT。

    返回 ``(token, 本地到期时间)``：token 用于响应；本地到期时间用于写
    ``user_session.access_expires_at``（D-4 本地墙上时间口径）。
    """
    if not secret_key:
        # 密钥缺失属配置错误：fail-fast，绝不落回默认值
        raise RuntimeError("SECRET_KEY 未配置：JWT 签名密钥必须来自环境变量（.env）")

    utc_now = _utc_now()
    minutes = int(access_minutes)
    payload = {
        "sub": str(int(user_id)),
        "jti": str(jti),
        "iat": int(utc_now.timestamp()),
        "exp": int((utc_now + timedelta(minutes=minutes)).timestamp()),
    }
    token = jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)
    return token, now_local() + timedelta(minutes=minutes)


def decode_access_token(token: str, secret_key: str) -> dict:
    """校验并解析 Access JWT；任何失败统一抛 ``401 UNAUTHENTICATED``。"""
    if not token:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:  # 过期 / 篡改 / 算法不符 / 格式错误 —— 统一口径
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    if not payload.get("sub") or not payload.get("jti"):
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    return payload


__all__ = [
    "PASSWORD_MIN_LEN",
    "PASSWORD_MAX_LEN",
    "USERNAME_MIN_LEN",
    "USERNAME_MAX_LEN",
    "REFRESH_HASH_LEN",
    "now_local",
    "format_dt",
    "normalize_password",
    "hash_password",
    "verify_password",
    "dummy_verify",
    "check_password_rule",
    "normalize_username",
    "check_username_rule",
    "generate_refresh_token",
    "hash_refresh_token",
    "generate_access_token_id",
    "create_access_token",
    "decode_access_token",
]
