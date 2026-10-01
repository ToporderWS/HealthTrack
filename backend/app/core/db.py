# -*- coding: utf-8 -*-
"""数据库引擎与会话管理。

设计说明：
- 使用 **SQLAlchemy 2.x 原生**（``create_engine`` / ``sessionmaker``），
  不额外引入 ORM 集成层，严格贴合 S1-D 冻结技术栈。
- ``pool_pre_ping=True`` 避免空闲断连（S1-D §4.3）。
- 请求级会话存放于 ``flask.g``，由 ``teardown_appcontext`` 统一关闭。
- **本模块不定义任何业务查询**（业务逻辑属后续批次）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from flask import Flask, g
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def init_engine(app: Flask) -> Engine:
    """按应用配置创建引擎与会话工厂（在应用工厂中调用一次）。"""
    global _engine, _session_factory
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
    _engine = create_engine(uri, **options)
    _session_factory = sessionmaker(
        bind=_engine, autoflush=False, expire_on_commit=False, future=True
    )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("数据库引擎尚未初始化：请先调用 init_engine(app)")
    return _engine


def get_session_factory() -> sessionmaker:
    if _session_factory is None:
        raise RuntimeError("会话工厂尚未初始化：请先调用 init_engine(app)")
    return _session_factory


def get_db() -> Session:
    """获取当前请求的数据库会话（懒创建，随请求结束关闭）。"""
    if "db_session" not in g:
        g.db_session = get_session_factory()()
    return g.db_session


def close_db(exc: Optional[BaseException] = None) -> None:
    """请求结束/异常时释放会话。"""
    session = g.pop("db_session", None)
    if session is not None:
        try:
            if exc is not None:
                session.rollback()
        finally:
            session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """脚本 / 定时任务使用的会话上下文（自动提交或回滚）。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> bool:
    """连通性探测（仅执行 ``SELECT 1``，不做任何业务查询）。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
