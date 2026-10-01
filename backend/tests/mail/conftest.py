# -*- coding: utf-8 -*-
"""MAIL-DELIVERY-1 —— pytest 装置（**独立目录** ``tests/mail/``）。

为什么另建 ``tests/mail/``
--------------------------
授权 §十三 把「本批 Mock SMTP 测试矩阵（44 项）」列为**独立计数单元**
⇒ 必须可与既有 ``tests/b2``＝47 / ``tests/b3``＝21 分离计数。

复用 B1-R-FIX 封板的四重保护（**本装置不重复实现任何一层**）
-----------------------------------------------------------
- **D0**：``backend/conftest.py`` 已把 ``MYSQL_DB`` 钉死为 ``kangji_healthtrack_test``
  （fail-closed；pytest 内**无法**落到开发库）；
- **B 本批独占前缀**：账号一律 ``tstmail`` + 6 位 hex（``tstmail`` ⊂ ``tst%``）；
- **C 本次创建集合**：清理按「前缀 ＋ 用例启动时 id 水位线」双条件；
- **A denylist**：``testsafety`` 引擎级咽喉点保护 ``top001`` 等 4 个保护账号。

⚠️ **零真实网络**：本目录所有用例一律以 ``monkeypatch`` 替换
``mail_service.smtplib.SMTP`` 为伪实现；``socket`` 级连接在本目录**永不会发生**
（另有 ``test_ar_no_real_network`` 以「无替换即失败」的方式反证）。
"""
from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy import delete, select, text

from app.core.db import get_engine, get_session_factory
from app.core.password_reset import normalize_email
from app.models import ALL_TABLES
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode
from app.services import mail_service

#: 与全仓统一：测试账号前缀（``tst``）；本批再叠独占 tag ``mail``
TEST_PREFIX = "tst"
BATCH_TAG = "mail"

#: 清理范围 = V1.0 全部 10 张业务表（不含 ``alembic_version``）
GUARDED_TABLES = tuple(ALL_TABLES)

API = "/api/v1"
DEFAULT_PASSWORD = "abc12345"

#: **测试专用** pepper（伪造值；绝非任何环境真实密钥，不出现在任何配置文件里）
TEST_PEPPER = "mail-test-only-pepper-DO-NOT-USE-IN-PROD"

#: **本批专用** 伪造 SMTP 口令（明显虚构；授权 §六 明示允许的形态）
FAKE_SMTP_PASSWORD = "dummy-app-password"


# ══════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════
def unique_username(tag: str = BATCH_TAG) -> str:
    """唯一测试用户名（``tst`` + tag + 6 hex，≤ 20 位且字母开头）。"""
    return f"{TEST_PREFIX}{tag}{secrets.token_hex(3)}"


def unique_email(prefix: str = "mail") -> str:
    """唯一测试邮箱（示例域，**不真实投递**）。"""
    return f"{prefix}{secrets.token_hex(4)}@example.com"


def counts() -> Dict[str, int]:
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def max_ids() -> Dict[str, int]:
    """全部受管表当前 ``MAX(id)`` 水位线（每个用例开始时取值）。"""
    with get_engine().connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT COALESCE(MAX(id),0) FROM `{t}`")).scalar() or 0)
            for t in GUARDED_TABLES
        }


def purge_mail_rows(baseline_max: Dict[str, int]) -> None:
    """回收**本模块**写入的行（前缀 ＋ id 水位线双条件；不越界清别的模块）。"""
    factory = get_session_factory()
    with factory() as db:
        ids = [
            int(r[0])
            for r in db.execute(
                select(UserAccount.id).where(
                    UserAccount.username.like(f"{TEST_PREFIX}%"),
                    UserAccount.id > baseline_max["user_account"],
                )
            ).all()
        ]
        if ids:
            db.execute(delete(VerificationCode).where(VerificationCode.user_id.in_(ids)))
            db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id.in_(ids)))
            db.execute(delete(UserSession).where(UserSession.user_id.in_(ids)))
            db.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))
            db.execute(delete(UserAccount).where(UserAccount.id.in_(ids)))
        db.execute(
            delete(LoginFailureState).where(
                LoginFailureState.username.like(f"{TEST_PREFIX}%"),
                LoginFailureState.id > baseline_max["login_failure_state"],
            )
        )
        db.execute(
            delete(VerificationCode).where(VerificationCode.id > baseline_max["verification_code"])
        )
        db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.id > baseline_max["password_reset_token"]
            )
        )
        db.commit()


def exec_sql(sql: str, **params) -> None:
    """测试专用：构造特殊状态（如回拨冷却时间窗）。"""
    factory = get_session_factory()
    with factory() as db:
        db.execute(text(sql), params)
        db.commit()


def rows(sql: str, **params) -> List[Any]:
    factory = get_session_factory()
    with factory() as db:
        return db.execute(text(sql), params).all()


def one(sql: str, **params):
    factory = get_session_factory()
    with factory() as db:
        return db.execute(text(sql), params).scalar()


# ══════════════════════════════════════════════════════════════════
# HTTP 助手
# ══════════════════════════════════════════════════════════════════
def register_account(
    client, *, username: Optional[str] = None, password: str = DEFAULT_PASSWORD
) -> Tuple[str, int]:
    """通过真实 A-01 契约注册（``auto_login=True``）；返回 ``(username, user_id)``。"""
    username = username or unique_username()
    resp = client.post(
        f"{API}/auth/register",
        json={
            "username": username,
            "password": password,
            "agreement_version": "v1.0",
            "agreement_accepted": True,
            "auto_login": True,
        },
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    uid = int(resp.get_json()["data"]["user"]["user_id"])
    return username, uid


def access_token_of(client, username: str, password: str = DEFAULT_PASSWORD) -> str:
    resp = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return str(resp.get_json()["data"]["tokens"]["access_token"])


def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def req_reset(client, username: str):
    """PR-01 发起找回。"""
    return client.post(f"{API}/auth/password-reset/request", json={"username": username})


def req_bind(client, token: str, email: Any, password: Any = DEFAULT_PASSWORD):
    """PR-04 发起邮箱绑定。"""
    return client.post(
        f"{API}/auth/email/bind-request",
        headers=auth_header(token),
        json={"email": email, "current_password": password},
    )


def req_verify_reset(client, username: str, code: Any):
    return client.post(
        f"{API}/auth/password-reset/verify", json={"username": username, "code": code}
    )


def identity_of(resp) -> Dict[str, Any]:
    """把响应归一化为**可恒等比较**的业务体。

    为什么需要：统一响应外壳含 ``request_id``（**每次唯一**，用于日志关联），
    它**不是**业务字段 —— 防枚举判据关心的是「业务形态是否可区分」。
    本助手剥离 ``request_id``，其余字段**逐字保留**（含 ``data`` 是否为 ``None``）。
    """
    body = dict(resp.get_json() or {})
    body.pop("request_id", None)
    return body


def set_email_verified(uid: int, email: str) -> None:
    """测试装置：把账号直接置为「已绑定且已验证」的邮箱（**仅测试库**）。

    用途：让 PR-01 具备「可发送」充分必要条件（① 存在 ② email 非空 ③ 已验证）。
    注意：这是**测试装置技巧**，绕过 PR-04/PR-05 正常绑定流，只用于构造前置状态。
    """
    exec_sql(
        "UPDATE user_account SET email=:e, email_verified_at=NOW() WHERE id=:u",
        e=normalize_email(email),
        u=int(uid),
    )


def rewind_reset_cooldown(uid: int, seconds: int = 120) -> None:
    """把 ``password_reset`` 验证码的 ``created_at`` 回拨，解除 60s 冷却。

    **仅测试装置技巧**，不改变产品语义。
    """
    exec_sql(
        "UPDATE verification_code SET created_at = DATE_SUB(created_at, INTERVAL :s SECOND) "
        "WHERE user_id=:u AND purpose='password_reset'",
        s=seconds,
        u=int(uid),
    )


def latest_bind_code_for(email: str) -> Optional[str]:
    """从**内存投递箱**取发给该邮箱的最新一封 ``email_bind`` 邮件验证码。

    ⚠️ 只在 ``MAIL_BACKEND=memory`` 下可用 —— 读的是**投递载荷**（邮件等价物），
    **不是**日志、**也不是** DB 明文（DB 里只有 ``code_hash``）。
    """
    from app.core.password_reset import PURPOSE_EMAIL_BIND

    target = normalize_email(email)
    for item in reversed(mail_service.memory_outbox()):
        if item.get("purpose") != PURPOSE_EMAIL_BIND:
            continue
        if normalize_email(item.get("to")) == target:
            return str(item.get("code"))
    return None


# ══════════════════════════════════════════════════════════════════
# SMTP 伪实现（**零真实网络**）
# ══════════════════════════════════════════════════════════════════
class FakeSMTP:
    """``smtplib.SMTP`` 的伪实现：记录调用序列，可注入任一阶段故障。

    支持两种故障注入方式（授权 §十三 P~U）：
    1. **实例时**：构造参数 ``on_connect`` / ``on_starttls`` / ``on_login`` / ``on_send``；
    2. **类级**（推荐，供 ``monkeypatch.setattr`` 前设置）：
       ``FakeSMTP.fail_on = "connect"|"starttls"|"login"|"send"`` ＋
       ``FakeSMTP.fail_exc = <Exception instance>``
    """

    instances: List["FakeSMTP"] = []
    #: 类级故障注入点（``None`` ⇒ 正常）；每个用例由 fixture 复位
    fail_on: Optional[str] = None
    #: 类级故障异常实例（默认按阶段选合适的 SMTP 异常）
    fail_exc: Optional[BaseException] = None

    def __init__(
        self,
        host: Any = None,
        port: Any = None,
        timeout: Any = None,
        *,
        on_connect: Optional[BaseException] = None,
        on_starttls: Optional[BaseException] = None,
        on_login: Optional[BaseException] = None,
        on_send: Optional[BaseException] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: List[str] = []
        self.tls_started = False
        self.logged_in: Optional[Tuple[str, str]] = None
        self.sent: List[Any] = []
        self._closed = False
        self._injected = {
            "starttls": on_starttls,
            "login": on_login,
            "send_message": on_send,
        }
        FakeSMTP.instances.append(self)
        if on_connect is not None:
            raise on_connect
        # ── 类级注入：connect 阶段 ──
        if FakeSMTP.fail_on == "connect" and FakeSMTP.fail_exc is not None:
            raise FakeSMTP.fail_exc

    # ── 上下文管理器协议（实现须优先使用 ``with smtplib.SMTP(...) as s``）──
    def __enter__(self) -> "FakeSMTP":
        self.calls.append("__enter__")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.calls.append("__exit__")
        self._closed = True
        return False

    # ── SMTP 协议面 ──
    def ehlo(self, *args, **kwargs):
        self.calls.append("ehlo")
        return (250, b"ok")

    def starttls(self, *args, **kwargs):
        self.calls.append("starttls")
        exc = self._injected["starttls"]
        if exc is not None:
            raise exc
        if FakeSMTP.fail_on == "starttls" and FakeSMTP.fail_exc is not None:
            raise FakeSMTP.fail_exc
        self.tls_started = True
        return (220, b"ready")

    def login(self, username, password):
        self.calls.append("login")
        exc = self._injected["login"]
        if exc is not None:
            raise exc
        if FakeSMTP.fail_on == "login" and FakeSMTP.fail_exc is not None:
            raise FakeSMTP.fail_exc
        self.logged_in = (username, password)
        return (235, b"auth ok")

    def send_message(self, message, *args, **kwargs):
        self.calls.append("send_message")
        exc = self._injected["send_message"]
        if exc is not None:
            raise exc
        if FakeSMTP.fail_on == "send" and FakeSMTP.fail_exc is not None:
            raise FakeSMTP.fail_exc
        self.sent.append(message)
        return {}

    def quit(self):
        self.calls.append("quit")
        self._closed = True
        return (221, b"bye")

    def close(self):
        self.calls.append("close")
        self._closed = True


@pytest.fixture()
def fake_smtp(monkeypatch):
    """把 ``smtplib.SMTP`` 换成 :class:`FakeSMTP`，并返回该伪类。

    **为什么 patch 标准库 ``smtplib`` 模块而不是 ``mail_service.smtplib``**：
    产品实现无论以 ``import smtplib`` / ``from smtplib import SMTP`` 哪种形态引用，
    最终都落在标准库模块对象上；直接替换标准库属性 ⇒ 对两种写法都生效，
    且**不依赖** ``mail_service`` 是否已暴露 ``smtplib`` 名字（避免把
    「模块未导入」这类装置层问题伪装成判据失败）。
    """
    import smtplib as _smtplib_mod

    FakeSMTP.instances = []
    FakeSMTP.fail_on = None
    FakeSMTP.fail_exc = None
    monkeypatch.setattr(_smtplib_mod, "SMTP", FakeSMTP)
    yield FakeSMTP
    FakeSMTP.fail_on = None
    FakeSMTP.fail_exc = None


def smtp_cfg(**overrides) -> Dict[str, Any]:
    """构造一份「配置齐全」的 smtp 后端 cfg（**全部为伪造值**）。"""
    cfg: Dict[str, Any] = {
        "MAIL_BACKEND": "smtp",
        "SMTP_HOST": "smtp.example.invalid",
        "SMTP_PORT": "587",
        "SMTP_USE_TLS": "true",
        "SMTP_USERNAME": "healthtrack@example.invalid",
        "SMTP_PASSWORD": FAKE_SMTP_PASSWORD,
        "SMTP_FROM": "no-reply@example.invalid",
        "SMTP_TIMEOUT": "10",
    }
    cfg.update(overrides)
    return cfg


# ══════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _test_pepper(app):  # noqa: ANN001
    """注入**测试专用** pepper（不依赖启动环境变量；结束时还原）。"""
    prev = app.config.get("PASSWORD_RESET_PEPPER")
    app.config["PASSWORD_RESET_PEPPER"] = TEST_PEPPER
    yield
    app.config["PASSWORD_RESET_PEPPER"] = prev


@pytest.fixture(autouse=True)
def _clear_mailbox(app):  # noqa: ANN001
    """每次用例前后清空内存投递箱，避免跨用例串味。"""
    mail_service.drain_memory_outbox()
    yield
    mail_service.drain_memory_outbox()


@pytest.fixture(autouse=True)
def _mail_scope_guard(app):  # noqa: ANN001
    """用例级测试数据守卫：前后对 10 张表取快照，结束清理并断言逐表还原。"""
    before = counts()
    baseline_max = max_ids()
    yield
    purge_mail_rows(baseline_max)
    after = counts()
    assert after == before, f"mail 测试数据未完全清理：before={before} after={after}"
