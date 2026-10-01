# -*- coding: utf-8 -*-
"""应用工厂（Flask 3.x）。

依据：《S1-D-技术方案最终冻结》技术架构。

顺序：加载配置 → 日志 → request_id → 错误处理 → 数据库引擎 → 模型 → 蓝图。
**本批不实现任何业务功能**。
"""
from __future__ import annotations

import logging
from typing import Optional

from flask import Flask

from app.core.auth import register_identity_guard
from app.core.config import load_config
from app.core.cors import register_dev_cors
from app.core.db import close_db, init_engine
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import register_request_id

logger = logging.getLogger(__name__)

API_V1_PREFIX = "/api/v1"


def create_app(app_env: Optional[str] = None) -> Flask:
    """创建并配置 Flask 应用。"""
    app = Flask(__name__)

    # 1) 配置（含环境隔离与生产 fail-fast）
    app.config.update(load_config(app_env))

    # 2) 日志（含隐私脱敏过滤器）
    configure_logging(app)

    # 3) request_id（服务端生成 + 响应头 X-Request-Id）
    register_request_id(app)

    # 3.1) H5 开发环境 CORS（**仅 APP_ENV=development 注册**；test/production 下为 no-op）
    register_dev_cors(app)

    # 4) 统一错误处理（18 个冻结错误码 ＋ B3 追加 EMAIL_TAKEN）
    register_error_handlers(app)

    # 5) 身份守卫：请求中出现 user_id → 400（user_id 只能由服务端从 Token 解析）
    register_identity_guard(app)

    # 6) 数据库引擎（本批仅建立引擎，不建表、不执行迁移）
    init_engine(app)
    app.teardown_appcontext(close_db)

    # 7) 导入 ORM 模型，确保 Base.metadata 完整（供 Alembic 使用）
    from app import models  # noqa: F401

    # 8) 路由：Y-01 健康检查 + S2 第二批 A-01~A-06 + S2 第三批 P/R + S2 第四批 G
    #    + S2 第五批 S（首页 / 统计 / 趋势）+ S2 第六批 E（数据导出）
    #    + S2 第七批 D（数据总览 / 清空全部数据）+ S2 第八批 A-07（注销账号）
    #    + S4-2 头像（AV-01 / AV-02 / AV-03）
    #    + B2 找回密码（PR-01 / PR-02 / PR-03）
    #    + B3 邮箱绑定（PR-04 / PR-05）
    from app.api.v1.account import bp as account_bp
    from app.api.v1.auth import bp as auth_bp
    from app.api.v1.avatar import bp as avatar_bp
    from app.api.v1.data import bp as data_bp
    from app.api.v1.email_bind import bp as email_bind_bp
    from app.api.v1.exports import bp as exports_bp
    from app.api.v1.goals import bp as goals_bp
    from app.api.v1.health import bp as health_bp
    from app.api.v1.password_reset import bp as password_reset_bp
    from app.api.v1.profile import bp as profile_bp
    from app.api.v1.records import bp as records_bp
    from app.api.v1.stats import bp as stats_bp
    from app.api.v1.users import bp as users_bp

    app.register_blueprint(health_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(auth_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(users_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(profile_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(avatar_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(records_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(goals_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(stats_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(exports_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(data_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(account_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(email_bind_bp, url_prefix=API_V1_PREFIX)
    app.register_blueprint(password_reset_bp, url_prefix=API_V1_PREFIX)

    logger.info(
        "应用已初始化：APP_ENV=%s，已注册蓝图=health/auth/users/profile/avatar/records/goals/stats/exports/data/account/password_reset/email_bind（%s）",
        app.config.get("APP_ENV"),
        API_V1_PREFIX,
    )
    return app


__all__ = ["create_app"]
