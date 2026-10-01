# -*- coding: utf-8 -*-
"""邮箱绑定（A2）—— 服务层（**B3 第一批**：PR-04 / PR-05）。

依据（**逐条落实，不发明规则**）
------------------------------
- 需求方 B3 授权（2026-09-24）§二（请求模型）／§四（绑定事务语义）／§五（安全要求）；
- 《忘记密码自助找回 · B3 开工前只读预检与实施方案》§7 方案甲／§8.2 契约表／§10 安全模型／§12 测试矩阵；
- **策略常量的唯一来源** :mod:`app.core.password_reset`（本模块**不重复定义任何数字**）。

本模块解决的真实缺口
--------------------
``PR-01/02/03`` 已在 B2 就绪，但「普通用户如何获得一个 ``email_verified_at`` 非空的邮箱」
**没有任何途径** ⇒ 自助找回链路**断路**（4 个存量账号 ``email`` 全 NULL，可用率 0%）。
本模块补齐这条**唯一的断点**：``bind-request`` → 邮件收码 → ``bind-confirm`` → 落 ``email``
＋ ``email_verified_at``。

冻结口径速览（全部来自 ``core/password_reset.py``）
--------------------------------------------------
| 项 | 值 | 常量 |
|---|---|---|
| 验证码 TTL | 15 分钟 | ``CODE_TTL_MINUTES`` |
| 校验失败上限 | 5 次（达上限即作废该码） | ``CODE_MAX_ATTEMPTS`` |
| 同账号同 purpose 有效码 | **1**（签发新码 ⇒ 旧码立即失效） | ``CODE_MAX_ACTIVE_PER_PURPOSE`` |
| 重发冷却 | 60 秒 | ``RESEND_COOLDOWN_SECONDS`` |

三处**关键设计裁定**（详见对应函数 docstring）
--------------------------------------------
1. **邮箱并入验证码 HMAC 主体**（:func:`_code_subject`）—— 授权 §四.2 要求
   「``email`` 必须与本次验证码挑战目标一致」，而 ``verification_code`` **没有** email 列
   且本批**禁止**加列 ⇒ 只能把邮箱前置进 ``code`` 的位置，使 HMAC 主体变为
   ``"{user_id}:email_bind:{email}:{code}"``。**零结构变更**即可保证「码只对被请求的邮箱有效」。
2. **不引入新的错误码**（授权 §二）—— 当前密码错误沿用既有 ``422 PASSWORD_INVALID``。
3. **成功事务 = 写 ``email`` ＋ 写 ``email_verified_at`` ＋ 消费验证码**（授权 §四.2），
   唯一冲突由 ``uk_user_account_email`` 兜底 ⇒ 捕获 ``IntegrityError`` ⇒ ``409 EMAIL_TAKEN``，
   **整事务回滚（不允许半写入）**。

安全边界（**与 B2 保持一致，不降低任何一项**）
-------------------------------------------
- 两个接口**均需登录**（``@require_auth``）；身份**只**来自 ``current_user``；
  ``user_id`` **只**能由服务端从 Access Token 解析（全局身份守卫兜底 ``400``）。
- **邮箱绑定不是密码找回**：本模块**不**撤销任何 Session（授权 §Q-B3-11）。
- **不得**让 ``email_bind`` 的码通过 ``password_reset`` 校验（反之亦然）——
  ``purpose`` 参与 HMAC 消息体 ⇒ 结构上不可能（``core/password_reset.py`` 冻结注释）。
- 验证码**绝不落库明文**（表只有 ``code_hash``）；**绝不落日志**（``core/logging.py`` 已覆盖
  ``email`` / ``verification_code`` / ``code_hash`` / ``password`` 等键）。

事务约定：服务层**自行 commit**（与 ``auth_service`` / ``password_reset_service`` 一致）。
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.errors import (
    ApiError,
    ErrorCode,
    FieldErrorCode,
    field_error,
    validation_error,
)
from app.core.password_reset import (
    CODE_LENGTH as _CODE_LENGTH,
    CODE_MAX_ACTIVE_PER_PURPOSE,
    CODE_MAX_ATTEMPTS,
    CODE_TTL_MINUTES,
    PURPOSE_EMAIL_BIND,
    RESEND_COOLDOWN_SECONDS,
    generate_verification_code,
    hash_verification_code,
    is_valid_email,
    normalize_email,
    require_pepper,
    verify_verification_code,
)
from app.core.security import now_local, verify_password
from app.models.user_account import UserAccount
from app.models.verification_code import VerificationCode

logger = logging.getLogger(__name__)

#: PR-04 **恒等响应**文案（冻结）。
#: 三分支（可绑定并已发信 / 冷却期内未重发 / 邮箱已被他人占用）**共用同一文案** ⇒
#: 请求方**无法**据此判断「目标邮箱是否已被占用」（授权 §五「不得降低防枚举」）。
REQUEST_MESSAGE = "如果该邮箱可绑定，我们已发送验证码"
#: PR-05 成功文案
CONFIRM_OK_MESSAGE = "邮箱绑定成功"
#: PR-05 失败文案（**唯一**；不区分「码错 / 码过期 / 从未申请 / 目标邮箱不符」）
INVALID_CODE_MESSAGE = "验证码不正确或已过期"

#: 投递后端名（仅用于**脱敏**告警，不含任何账号标识）
DEFAULT_MAIL_BACKEND_LABEL = "memory"

#: **本批未实现 / 待裁定**（如实登记，**不宣称"已消除"**）
open_items = (
    "current_password 校验**未**引入会话级失败计数：``user_session`` 现有计数字段"
    "仅 ``export_pwd_fail_count`` / ``change_pwd_fail_count``（分属导出与改密），"
    "新增字段须 migration ⇒ 本批**禁止**；复用 ``change_pwd_fail_count`` 会改变已封板 A-05 "
    "的可用尝试次数 ⇒ **未采用**，留待裁定（``Q-B3-12``）。",
    "账号级 / IP 级频控未实现（与 PR-01 同口径；``B1`` 表结构刻意不落 request_ip）。",
)

#: 等量开销专用固定码（**非真实验证码**；仅用于拉平「无有效挑战码」分支的耗时）
_PROBE_CODE = "0" * _CODE_LENGTH


# ══════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════
def _code_subject(email: str, code: str) -> str:
    """把**目标邮箱**并入验证码的 HMAC 主体：``"{规范化邮箱}:{code}"``。

    为什么**必须**这么做（授权 §四.2「``email`` 必须与本次验证码挑战目标一致」）
    ----------------------------------------------------------------------------
    ``verification_code``（B1 冻结）**只有** ``user_id`` / ``purpose`` / ``code_hash``，
    **没有** email 列，而本批**禁止**新增表 / 新增列（授权 §三）。
    若把 6 位明文码直接交给 :func:`hash_verification_code`，则 HMAC 主体为
    ``"{user_id}:email_bind:{code}"`` —— **同一串数字对被请求的邮箱无区分度**：
    攻击者可「**为 A 邮箱申请码、却用该码确认绑定 B 邮箱**」，即**从未证明对 B 的控制权**
    就完成绑定（越权绑定 + 后续用 B 走密码找回 ⇒ 账号接管）。

    把规范化邮箱前置进 ``code`` 的位置后，HMAC 主体变为
    ``"{user_id}:email_bind:{email}:{code}"`` ⇒ **同一串数字对不同邮箱得到不同摘要**，
    结构上保证「一条码只对被请求的那个邮箱有效」。**复用冻结原语、零结构变更。**

    ⚠️ 本函数**不改变** ``core/password_reset.py``（B1 冻结件），只是把
    ``code`` 这个自由字符串参数用作「邮箱 + 码」的复合体。
    """
    return "%s:%s" % (normalize_email(email), str(code))


def _consume_outstanding_bind_codes(db: OrmSession, user_id: int, now) -> None:
    """作废该账号 ``email_bind`` 用途下**全部未消费**的验证码（``CODE_MAX_ACTIVE_PER_PURPOSE``）。"""
    db.execute(
        update(VerificationCode)
        .where(
            VerificationCode.user_id == int(user_id),
            VerificationCode.purpose == PURPOSE_EMAIL_BIND,
            VerificationCode.consumed_at.is_(None),
        )
        .execution_options(synchronize_session=False)
        .values(consumed_at=now)
    )


def _latest_bind_challenge(
    db: OrmSession, user_id: int, *, for_update: bool = False
) -> Optional[VerificationCode]:
    """取该账号 ``email_bind`` 用途「当前唯一未消费」的挑战码。

    ``for_update=True`` ⇒ ``SELECT ... FOR UPDATE`` 行锁（并发 ``bind-confirm`` 只有一次能成功）。
    """
    stmt = (
        select(VerificationCode)
        .where(
            VerificationCode.user_id == int(user_id),
            VerificationCode.purpose == PURPOSE_EMAIL_BIND,
            VerificationCode.consumed_at.is_(None),
        )
        .order_by(VerificationCode.id.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalars().first()


def _equal_cost_probe(pepper: str, user_id: int, email: str) -> None:
    """**恒等耗时探针**：执行一次与「真实验证」等价的 HMAC 计算并丢弃结果。

    用于「无有效挑战码」等本可直接返回的分支，使各分支**计算量一致**（沿用 B2 既有思想）。
    """
    try:
        hash_verification_code(pepper, user_id, PURPOSE_EMAIL_BIND, _code_subject(email, _PROBE_CODE))
    except Exception:  # noqa: BLE001 —— 探针绝不改变控制流
        pass


def _invalid_code_error() -> ApiError:
    """PR-05 统一失败：``422 VALIDATION_FAILED`` ＋ 唯一中性文案。"""
    return validation_error(
        [field_error("code", FieldErrorCode.INVALID_FORMAT, INVALID_CODE_MESSAGE)]
    )


def _normalized_valid_email(email_raw: Any) -> str:
    """规范化 + 格式校验；非法 ⇒ ``422``（``errors[].field="email"``, ``INVALID_FORMAT``）。"""
    email = normalize_email(email_raw)
    if not is_valid_email(email):
        raise validation_error(
            [field_error("email", FieldErrorCode.INVALID_FORMAT, "邮箱格式不正确")]
        )
    return email


def _require_current_password(account: UserAccount, current_password_raw: Any) -> None:
    """复验**当前密码**（授权 §Q-B3-05：邮箱是密码找回安全因子 ⇒ 敏感操作）。

    失败语义：**沿用项目既有密码验证错误语义**（``422 PASSWORD_INVALID``，
    与 A-05 修改密码一致），**不新增**任何重复错误码（授权 §二）。
    """
    from app.core.security import normalize_password

    if not verify_password(normalize_password(current_password_raw), account.password_hash):
        raise ApiError(ErrorCode.PASSWORD_INVALID)


# ══════════════════════════════════════════════════════════════════
# PR-04 发起邮箱绑定（发验证码）
# ══════════════════════════════════════════════════════════════════
def request_email_bind(
    db: OrmSession,
    cfg: Dict[str, Any],
    *,
    account: UserAccount,
    email_raw: Any,
    current_password_raw: Any,
    mailer=None,
) -> Dict[str, Any]:
    """PR-04：为**当前登录账号**发起邮箱绑定（或改绑）。

    **对外恒等响应**：可绑定 / 冷却期内 / 邮箱已被占用 ⇒ 同一 ``message`` ＋ ``data: None``。
    **本阶段绝不写 ``user_account.email``**（授权 §四.1 / §Q-B3-04）。

    校验顺序（**顺序即安全**）：① 当前密码 → ② 邮箱规范化与格式 → ③ 重发冷却 → ④ 签发新码。
    """
    _require_current_password(account, current_password_raw)
    email = _normalized_valid_email(email_raw)

    pepper = require_pepper(cfg.get("PASSWORD_RESET_PEPPER"))
    user_id = int(account.id)
    now = now_local()

    # ── 重发冷却（服务端权威；不依赖前端倒计时）──
    last_created = db.execute(
        select(func.max(VerificationCode.created_at)).where(
            VerificationCode.user_id == user_id,
            VerificationCode.purpose == PURPOSE_EMAIL_BIND,
        )
    ).scalar()
    if last_created is not None and (now - last_created) < timedelta(
        seconds=RESEND_COOLDOWN_SECONDS
    ):
        # 冷却期内：统一恒等响应、**不重复发信**；仍付等价开销
        _equal_cost_probe(pepper, user_id, email)
        return {"message": REQUEST_MESSAGE, "data": None}

    # ── 冷通过：作废旧码 → 生成新码 → 落库（只存 hash）→ 投递 ──
    if CODE_MAX_ACTIVE_PER_PURPOSE == 1:
        _consume_outstanding_bind_codes(db, user_id, now)

    code = generate_verification_code()
    db.add(
        VerificationCode(
            user_id=user_id,
            purpose=PURPOSE_EMAIL_BIND,
            code_hash=hash_verification_code(
                pepper, user_id, PURPOSE_EMAIL_BIND, _code_subject(email, code)
            ),
            expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
            consumed_at=None,
            attempt_count=0,
            created_at=now,
        )
    )
    db.commit()

    # ── 投递（**失败不改变对外响应**；只留脱敏告警）──
    sender = mailer
    if sender is None:
        from app.services import mail_service as sender  # 延迟导入：便于测试替换
    try:
        result = sender.send_email_bind_code(
            cfg, to_email=email, code=code, ttl_minutes=CODE_TTL_MINUTES
        )
        if not result.delivered:
            # 只记后端名与结果，**不记邮箱 / 验证码**
            logger.warning(
                "email_bind 投递未成功（backend=%s, detail=%s, request 已回复恒等响应）",
                result.backend,
                result.detail,
            )
    except Exception:  # noqa: BLE001 —— 投递层异常同样不得改变对外响应
        logger.exception("email_bind 投递异常（已按恒等响应处理）")

    logger.info("email_bind_request 结果=OK（不含任何账号标识）")
    return {"message": REQUEST_MESSAGE, "data": None}


# ══════════════════════════════════════════════════════════════════
# PR-05 校验验证码 → 落库绑定
# ══════════════════════════════════════════════════════════════════
def confirm_email_bind(
    db: OrmSession,
    cfg: Dict[str, Any],
    *,
    account: UserAccount,
    email_raw: Any,
    code_raw: Any,
    current_password_raw: Any,
) -> Dict[str, Any]:
    """PR-05：校验验证码并**在同一事务**内写 ``email`` ＋ ``email_verified_at`` ＋ 消费该码。

    成功 ⇒ ``{"email_bound": True}``。
    **改绑**：``email`` 被覆盖 ＋ ``email_verified_at`` 重置为 ``now`` ⇒ **旧邮箱立即失效**（§Q-B3-04）。
    **不撤销任何 Session**（§Q-B3-11）。

    失败语义：当前密码错 ``422 PASSWORD_INVALID``；码错 / 码过期 / 目标邮箱不符 ⇒
    **同一中性** ``422``（不可区分）；尝试达上限 ⇒ ``429 SESSION_VERIFY_ABORTED``；
    邮箱唯一冲突 ⇒ ``409 EMAIL_TAKEN``（整事务回滚，**无半写入**）。
    """
    _require_current_password(account, current_password_raw)
    email = _normalized_valid_email(email_raw)

    pepper = require_pepper(cfg.get("PASSWORD_RESET_PEPPER"))
    user_id = int(account.id)
    now = now_local()
    code = "" if code_raw is None else str(code_raw).strip()

    # 行锁：并发两次 confirm 只有一次能成功（「取该账号当前唯一有效码」）
    challenge = _latest_bind_challenge(db, user_id, for_update=True)

    if challenge is None:
        _equal_cost_probe(pepper, user_id, email)
        raise _invalid_code_error()

    if challenge.expires_at <= now:
        _equal_cost_probe(pepper, user_id, email)
        raise _invalid_code_error()

    # 防御：历史数据里已达上限的码（正常路径下不会出现）
    if int(challenge.attempt_count) >= CODE_MAX_ATTEMPTS:
        _consume_outstanding_bind_codes(db, user_id, now)
        db.commit()
        raise ApiError(ErrorCode.SESSION_VERIFY_ABORTED)

    matched = verify_verification_code(
        pepper,
        user_id,
        PURPOSE_EMAIL_BIND,
        _code_subject(email, code),
        challenge.code_hash,
    )
    if not matched:
        challenge.attempt_count = int(challenge.attempt_count) + 1
        if int(challenge.attempt_count) >= CODE_MAX_ATTEMPTS:
            # 达上限 ⇒ 该码作废，必须重新申请
            _consume_outstanding_bind_codes(db, user_id, now)
            db.commit()
            raise ApiError(ErrorCode.SESSION_VERIFY_ABORTED)
        db.commit()
        raise _invalid_code_error()

    # ── 成功：同一事务内「写 email ＋ 写 email_verified_at ＋ 消费验证码」──
    account.email = email
    account.email_verified_at = now
    account.updated_at = now
    _consume_outstanding_bind_codes(db, user_id, now)
    try:
        db.commit()
    except IntegrityError as exc:
        # ``uk_user_account_email`` 兜底：该邮箱已属于**其它**账号（并发下同样成立）
        db.rollback()
        if "email" in str(exc).lower():
            logger.info("email_bind_confirm 结果=EMAIL_TAKEN（不含任何账号标识）")
            raise ApiError(ErrorCode.EMAIL_TAKEN)
        raise

    logger.info("email_bind_confirm 结果=OK（不含任何账号标识 / 不含邮箱）")
    return {"message": CONFIRM_OK_MESSAGE, "data": {"email_bound": True}}


__all__ = [
    "REQUEST_MESSAGE",
    "CONFIRM_OK_MESSAGE",
    "INVALID_CODE_MESSAGE",
    "open_items",
    "request_email_bind",
    "confirm_email_bind",
]
