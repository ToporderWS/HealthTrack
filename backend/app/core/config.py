# -*- coding: utf-8 -*-
"""配置加载与环境隔离。

依据：
- 《S1-D-开发环境与工程实施准备》§4.1 三级配置隔离
- 《S1-D-开发环境与工程实施准备》§4.2 环境变量清单（.env.example 内容冻结）
- 《S1-D-开发环境与工程实施准备》§5.1 密钥存储原则（真实密钥只写 .env*，仓库只提交 .env.example）

规则：
1. ``APP_ENV`` ∈ {development, test, production}；**未设置时默认 development**。
2. 加载顺序：先读 ``backend/.env.<APP_ENV>``（环境模板/公共值），
   再读 ``backend/.env``（本机真实密钥，**覆盖前者**，见 §5.1「真实密钥只写 .env」）。
3. **生产环境若缺失必需变量 → 启动失败（fail-fast）**，不允许静默降级。
4. ``.env*`` 全部已被 .gitignore 排除；仓库只提交 ``.env.example``（全占位符）。
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

# backend/ 目录（本文件位于 backend/app/core/config.py）
BACKEND_DIR = Path(__file__).resolve().parents[2]

VALID_ENVS = ("development", "test", "production")
DEFAULT_ENV = "development"


def _is_placeholder(value) -> bool:
    """判定是否为「未配置 / 仍是占位符」。"""
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or "CHANGE_ME" in text.upper()


def _load_env_files(app_env: str) -> None:
    """加载环境变量文件（后者覆盖前者）。"""
    env_file = BACKEND_DIR / f".env.{app_env}"
    if env_file.exists():
        load_dotenv(env_file, override=False)
    base_env = BACKEND_DIR / ".env"
    if base_env.exists():
        # 本机真实密钥优先（§5.1）
        load_dotenv(base_env, override=True)


def _get(key: str, default=None):
    return os.environ.get(key, default)


def _get_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _resolve_dir(raw: str) -> str:
    """把相对目录解析为 backend/ 下的绝对路径。"""
    path = Path(str(raw))
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return str(path)


def build_db_uri(cfg: dict) -> str:
    """拼接 SQLAlchemy 连接串（强制 utf8mb4）。"""
    # 注意：SQLAlchemy 解析 URL 时对 userinfo 使用 urllib.parse.unquote（**非** unquote_plus），
    # 因此必须用 quote(safe="")：quote_plus 会把空格编码为 '+'，而 unquote 不会把 '+' 还原为空格，
    # 会导致「口令含空格」时认证失败。
    user = quote(str(cfg.get("MYSQL_USER") or ""), safe="")
    password = quote(str(cfg.get("MYSQL_PASSWORD") or ""), safe="")
    host = cfg.get("MYSQL_HOST") or "127.0.0.1"
    port = cfg.get("MYSQL_PORT") or 3306
    db = cfg.get("MYSQL_DB") or "kangji_healthtrack"
    charset = cfg.get("MYSQL_CHARSET") or "utf8mb4"
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset={charset}"


def _validate(cfg: dict) -> None:
    """生产环境 fail-fast；开发/测试允许未配置（骨架阶段不连业务库）。

    ``PASSWORD_RESET_PEPPER`` 亦为生产必需项（``CR-F006-001`` · B1）：找回密码是
    V1.0 发布前补齐功能，**缺少 pepper 时验证码哈希无法安全生成**，宁可启动失败
    也不允许静默降级为「无 pepper / 默认 pepper」。
    """
    if cfg["APP_ENV"] != "production":
        return
    required = (
        "SECRET_KEY",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DB",
        "PASSWORD_RESET_PEPPER",
    )
    missing = [k for k in required if _is_placeholder(cfg.get(k))]
    if missing:
        raise RuntimeError(
            "生产环境缺少必需配置（不得静默降级）：" + ", ".join(missing)
        )


def load_config(app_env: str | None = None) -> dict:
    """加载并返回配置字典。"""
    resolved = (app_env or os.environ.get("APP_ENV") or DEFAULT_ENV).strip().lower()
    if resolved not in VALID_ENVS:
        raise RuntimeError(
            f"APP_ENV 非法：{resolved!r}（可选 {' / '.join(VALID_ENVS)}）"
        )

    _load_env_files(resolved)

    cfg = {
        # ── 运行环境 ──
        "APP_ENV": resolved,
        "DEBUG": resolved == "development",
        # ── 安全密钥 ──
        "SECRET_KEY": _get("SECRET_KEY"),
        "BCRYPT_ROUNDS": _get_int("BCRYPT_ROUNDS", 12),
        # ── 找回密码 pepper（CR-F006-001 / B1）──
        # **独立于 SECRET_KEY**（不复用、不派生）：
        #   ① 用途分离 —— SECRET_KEY 泄露不应同时击穿验证码 HMAC；
        #   ② 可独立轮换 —— 轮换 pepper 不影响已签发的 Access/Refresh Token；
        #   ③ 名称自解释 —— 运维一眼可知其归属功能。
        # 真值只写 ``backend/.env``（gitignore）；缺失 / 占位符 ⇒ 生产 fail-fast；
        # 校验码明文与 pepper **均不得**进入日志（见 core/logging.py）。
        "PASSWORD_RESET_PEPPER": _get("PASSWORD_RESET_PEPPER"),
        # ── 邮件投递后端（CR-F006-001 / B2）──
        # 缺省 `memory`（进程内，测试/开发零副作用）；
        # 其余可选 `file-outbox` / `redacted-console` / `smtp`。
        # **MAIL-DELIVERY-1**：`smtp` 已为真实投递实现（标准库 smtplib）；
        # 其凭据**只从运行时环境读取**（绝不硬编码 / 绝不落盘 / 绝不进日志）。
        "MAIL_BACKEND": _get("MAIL_BACKEND", "memory"),
        # 出件箱目录（仅 `MAIL_BACKEND=file-outbox` 时使用；缺省不创建）
        "MAIL_OUTBOX_DIR": _get("MAIL_OUTBOX_DIR"),
        # ── SMTP 投递配置（MAIL-DELIVERY-1；**仅 MAIL_BACKEND=smtp 时使用**）──
        # 语义：缺 / 非法 ⇒ 该次投递 fail-closed（收敛为「未投递」，不影响对外响应）。
        # ⚠️ `SMTP_PASSWORD` 只写本机 `.env`（gitignore），仓库只保留 `.env.example` 占位说明。
        "SMTP_HOST": _get("SMTP_HOST", "smtp.gmail.com"),
        "SMTP_PORT": _get_int("SMTP_PORT", 587),
        # 布尔解析由 `services/mail_service._parse_use_tls` 统一负责
        # （**禁止** `bool("false")` 式错误解析；本处原样透传字符串）。
        "SMTP_USE_TLS": _get("SMTP_USE_TLS", "true"),
        "SMTP_USERNAME": _get("SMTP_USERNAME"),
        "SMTP_PASSWORD": _get("SMTP_PASSWORD"),
        "SMTP_FROM": _get("SMTP_FROM"),
        "SMTP_TIMEOUT": _get_int("SMTP_TIMEOUT", 10),
        # ── Token 有效期（承接 S1-A / S1-B）──
        "TOKEN_ACCESS_MINUTES": _get_int("TOKEN_ACCESS_MINUTES", 120),
        "TOKEN_REFRESH_DAYS": _get_int("TOKEN_REFRESH_DAYS", 30),
        # ── 登录失败锁定（承接 S1-A）──
        "LOGIN_MAX_FAILS": _get_int("LOGIN_MAX_FAILS", 5),
        "LOGIN_LOCK_MINUTES": _get_int("LOGIN_LOCK_MINUTES", 5),
        "LOGIN_LOCK_STEP_1_MINUTES": _get_int("LOGIN_LOCK_STEP_1_MINUTES", 15),
        "LOGIN_LOCK_STEP_2_MINUTES": _get_int("LOGIN_LOCK_STEP_2_MINUTES", 60),
        # ── 会话内验密上限（承接 S1-A）──
        "VERIFY_MAX_PASSWORD_CHANGE": _get_int("VERIFY_MAX_PASSWORD_CHANGE", 5),
        "VERIFY_MAX_EXPORT": _get_int("VERIFY_MAX_EXPORT", 3),
        # ── 数据库 ──
        "MYSQL_HOST": _get("MYSQL_HOST", "127.0.0.1"),
        "MYSQL_PORT": _get_int("MYSQL_PORT", 3306),
        "MYSQL_USER": _get("MYSQL_USER"),
        "MYSQL_PASSWORD": _get("MYSQL_PASSWORD"),
        "MYSQL_DB": _get("MYSQL_DB", "kangji_healthtrack"),
        "MYSQL_CHARSET": _get("MYSQL_CHARSET", "utf8mb4"),
        # ── 导出临时文件（承接 S1-B）──
        "EXPORT_DOWNLOAD_TTL_MINUTES": _get_int("EXPORT_DOWNLOAD_TTL_MINUTES", 10),
        "EXPORT_PURGE_MINUTES": _get_int("EXPORT_PURGE_MINUTES", 60),
        # ── 头像（S4-2；上限冻结 2 MiB = 2 * 1024 * 1024）──
        "AVATAR_MAX_BYTES": _get_int("AVATAR_MAX_BYTES", 2 * 1024 * 1024),
        # ── 日志（I-05 保留期待法律审核，先按可配 180 天）──
        "LOG_LEVEL": _get("LOG_LEVEL", "INFO"),
        "LOG_RETENTION_DAYS": _get_int("LOG_RETENTION_DAYS", 180),
        # ── 软删清理（仅 3 张记录型表适用）──
        "SOFT_DELETE_PURGE_DAYS": _get_int("SOFT_DELETE_PURGE_DAYS", 30),
    }

    cfg["EXPORT_DIR"] = _resolve_dir(_get("EXPORT_DIR", "./storage/exports"))
    cfg["AVATAR_DIR"] = _resolve_dir(_get("AVATAR_DIR", "./storage/avatars"))
    cfg["LOG_DIR"] = _resolve_dir(_get("LOG_DIR", "./logs"))

    cfg["SQLALCHEMY_DATABASE_URI"] = build_db_uri(cfg)
    cfg["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,   # 避免空闲断连（S1-D §4.3）
        "pool_size": 5,
        "max_overflow": 5,
        "pool_recycle": 3600,
    }

    _validate(cfg)
    return cfg
