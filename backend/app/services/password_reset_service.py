# -*- coding: utf-8 -*-
"""找回密码自助找回 —— 服务层（**B2**：PR-01 / PR-02 / PR-03）。

依据（**逐条落实，不发明规则**）
------------------------------
- ``CR-F006-001``（``F-006`` →「V1.0 发布前补齐功能」）
- 《S1-A-安全规则冻结清单》文末「变更登记」``SR-1``~``SR-13``
- 《忘记密码自助找回 · 开工前只读审计与方案报告》§5.4 参数表 / §6.2 接口契约 / §8.1 防枚举六条
- **策略常量的唯一来源** :mod:`app.core.password_reset`（本模块**不重复定义任何数字**）

冻结口径速览（全部来自 ``core/password_reset.py``）
--------------------------------------------------
| 项 | 值 | 常量 |
|---|---|---|
| 验证码 TTL | 15 分钟 | ``CODE_TTL_MINUTES`` |
| 校验失败上限 | 5 次（达上限即作废该码） | ``CODE_MAX_ATTEMPTS`` |
| 同账号同 purpose 有效码 | **1**（签发新码 ⇒ 旧码立即失效） | ``CODE_MAX_ACTIVE_PER_PURPOSE`` |
| 重发冷却 | 60 秒 | ``RESEND_COOLDOWN_SECONDS`` |
| reset token TTL | 15 分钟 | ``RESET_TOKEN_TTL_MINUTES`` |

防账号枚举（**六条同时成立才有效**，§8.1）
-----------------------------------------
① **四态恒等响应**：命中 / 不存在 / 未绑定邮箱 / 邮箱未验证 → 同 ``code`` ＋ 同 ``message``
   ＋ 同 HTTP ＋ 同 ``data``；
② **恒等耗时**：所有「不发送」分支都执行一次**等价 HMAC 计算**（见 :func:`_equal_cost_probe`）；
③ **不返回目标邮箱**：``data`` 恒为 ``null``，任何字段都不回显邮箱（即便掩码）；
④ **文案中性**：校验失败一律「验证码不正确或已过期」——**禁止**「该账号不存在」「未绑定邮箱」；
⑤ **投递失败不暴露**：发送失败仍 ``200`` ＋ 同 message，仅服务端**脱敏**告警；
⑥ **日志不含 username / email / code**（``core/logging.py`` 的键表已覆盖）。

残余风险（**如实登记，不宣称"已消除"**）：时序侧信道只能"拉平"而不能"归零"
（解释器调度、DB 缓存命中差异仍可能被高精度测量）；且**本批未实现账号级 / IP 级频控**
（见 :data:`unimplemented_rate_limits` 与验收报告"尚未完成项"）。

事务约定：服务层**自行 commit**（与 ``auth_service`` 一致）。
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
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
    PURPOSE_PASSWORD_RESET,
    RESEND_COOLDOWN_SECONDS,
    RESET_TOKEN_TTL_MINUTES,
    generate_reset_token,
    generate_verification_code,
    hash_reset_token,
    hash_verification_code,
    normalize_email,
    require_pepper,
    verify_verification_code,
)
from app.core.security import (
    check_password_rule,
    hash_password,
    normalize_password,
    normalize_username,
    now_local,
    verify_password,
)
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.verification_code import VerificationCode

logger = logging.getLogger(__name__)

#: PR-01 **恒等响应**文案（冻结；四态共用，**不得**按状态改写）
REQUEST_MESSAGE = "如果该账号存在且已绑定邮箱，我们已发送验证码"
#: PR-02 成功文案
VERIFY_OK_MESSAGE = "验证成功"
#: PR-02 失败文案（**唯一**；不区分"码错 / 码过期 / 码已用 / 从未申请"）
INVALID_CODE_MESSAGE = "验证码不正确或已过期"
#: PR-03 成功文案
CONFIRM_OK_MESSAGE = "密码已重置，请使用新密码登录"
#: PR-03 凭证无效文案（中性；不透露"无效"还是"已用"还是"过期"）
RESET_CREDENTIAL_INVALID_MESSAGE = "重置凭证无效或已过期，请重新发起找回"

#: ``user_session.revoked_reason`` 新增值（B2 授权 §七.13；``VARCHAR(24)`` 足够）
REASON_PASSWORD_RESET = "password_reset"

#: **本批未实现**的频控维度（如实登记，供需求方裁定）
unimplemented_rate_limits = (
    "账号级 小时/日 频控",
    "IP 级频控（B1 表结构刻意不落 request_ip ⇒ 当前无载体）",
)

#: 等量开销专用固定码（**非真实验证码**；仅用于拉平「不发送」分支的耗时）
_PROBE_CODE = "0" * _CODE_LENGTH


# ══════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════
def _get_account(db: OrmSession, username: str) -> Optional[UserAccount]:
    """按用户名（小写）取账号 —— 走唯一索引 ``uk_user_account_username``。"""
    return db.execute(
        select(UserAccount).where(UserAccount.username == username)
    ).scalars().first()


def _equal_cost_probe(pepper: str, user_id: int = 0) -> None:
    """**恒等耗时探针**：执行一次与「真实验证」等价的 HMAC 计算并丢弃结果。

    用于所有「本可以不计算结果就返回」的分支（账号不存在 / 未绑定邮箱 /
    冷却期内 / 无有效挑战码 …），使这些分支与「有码可校验」分支的**计算量相同**，
    避免通过响应时间区分账号状态（沿用 ``core.security.dummy_verify`` 的既有思想）。
    """
    try:
        hash_verification_code(pepper, user_id, PURPOSE_PASSWORD_RESET, _PROBE_CODE)
    except Exception:  # noqa: BLE001 —— 探针绝不改变控制流
        pass


def _invalid_code_error() -> ApiError:
    """PR-02 统一失败：``422 VALIDATION_FAILED`` ＋ 唯一中性文案。"""
    return validation_error(
        [field_error("code", FieldErrorCode.INVALID_FORMAT, INVALID_CODE_MESSAGE)]
    )


def _reset_credential_invalid() -> ApiError:
    """PR-03 统一失败：``401 UNAUTHENTICATED`` ＋ 中性文案（不区分失效原因）。"""
    return ApiError(
        ErrorCode.UNAUTHENTICATED,
        message=RESET_CREDENTIAL_INVALID_MESSAGE,
    )


def _consume_outstanding_codes(db: OrmSession, user_id: int, now) -> None:
    """作废该账号同 ``purpose`` 下**全部未消费**的验证码（``CODE_MAX_ACTIVE_PER_PURPOSE``）。"""
    db.execute(
        update(VerificationCode)
        .where(
            VerificationCode.user_id == int(user_id),
            VerificationCode.purpose == PURPOSE_PASSWORD_RESET,
            VerificationCode.consumed_at.is_(None),
        )
        .execution_options(synchronize_session=False)
        .values(consumed_at=now)
    )


def revoke_outstanding_reset_tokens(db: OrmSession, user_id: int, now=None) -> int:
    """作废该账号**全部未消费且未作废**的重置凭证（``E-24``）。

    返回受影响行数。**消费（``consumed_at``）与作废（``revoked_at``）语义互斥可辨** ——
    本函数只写 ``revoked_at``，与用户真实用过一次的 ``consumed_at`` 不混淆
    （见 ``models/password_reset_token.py`` 的设计说明）。
    """
    stamp = now or now_local()
    result = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == int(user_id),
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
        )
        .execution_options(synchronize_session=False)
        .values(revoked_at=stamp)
    )
    return int(result.rowcount or 0)


# ══════════════════════════════════════════════════════════════════
# PR-01 请求密码找回
# ══════════════════════════════════════════════════════════════════
def request_password_reset(
    db: OrmSession, cfg: Dict[str, Any], *, username_raw: Any, mailer=None
) -> Dict[str, Any]:
    """PR-01：发起找回。**对外恒等响应**（成功 / 不存在 / 未绑定 / 冷却中 四态一致）。

    ⇒ 返回 ``{"message": REQUEST_MESSAGE, "data": None}``，**不因分支而变**。

    内部真正生成验证码并投递的**充分必要条件**（三者同时成立）：
    ① 账号存在；② ``email`` 非空；③ ``email_verified_at`` 非空。
    """
    pepper = require_pepper(cfg.get("PASSWORD_RESET_PEPPER"))
    username = normalize_username(username_raw)
    now = now_local()

    account = _get_account(db, username)
    sendable = (
        account is not None
        and normalize_email(account.email) != ""
        and account.email_verified_at is not None
    )

    if not sendable:
        # 分支 ②③（不存在 / 未绑定 / 未验证）：等价开销后返回恒等响应
        _equal_cost_probe(pepper, int(account.id) if account is not None else 0)
        return {"message": REQUEST_MESSAGE, "data": None}

    user_id = int(account.id)

    # ── 重发冷却（服务端二次校验，不依赖前端倒计时）──
    last_created = db.execute(
        select(func.max(VerificationCode.created_at)).where(
            VerificationCode.user_id == user_id,
            VerificationCode.purpose == PURPOSE_PASSWORD_RESET,
        )
    ).scalar()
    if last_created is not None and (now - last_created) < timedelta(
        seconds=RESEND_COOLDOWN_SECONDS
    ):
        # 冷却期内：**统一 200 不发信**（Q-PR-5 冻结口径），但仍付等价开销
        _equal_cost_probe(pepper, user_id)
        return {"message": REQUEST_MESSAGE, "data": None}

    # ── 冷通过：作废旧码 → 生成新码 → 投递 ──
    if CODE_MAX_ACTIVE_PER_PURPOSE == 1:
        _consume_outstanding_codes(db, user_id, now)

    code = generate_verification_code()
    db.add(
        VerificationCode(
            user_id=user_id,
            purpose=PURPOSE_PASSWORD_RESET,
            code_hash=hash_verification_code(pepper, user_id, PURPOSE_PASSWORD_RESET, code),
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
        result = sender.send_password_reset_code(
            cfg,
            to_email=normalize_email(account.email),
            code=code,
            ttl_minutes=CODE_TTL_MINUTES,
        )
        if not result.delivered:
            # 只记后端名与结果，**不记邮箱 / 验证码**
            logger.warning(
                "password_reset 投递未成功（backend=%s, detail=%s, request 已回复 200 恒等）",
                result.backend,
                result.detail,
            )
    except Exception:  # noqa: BLE001 —— 投递层异常同样不得改变对外响应
        logger.exception("password_reset 投递异常（已按恒等响应处理）")

    return {"message": REQUEST_MESSAGE, "data": None}


# ══════════════════════════════════════════════════════════════════
# PR-02 校验验证码 → 签发一次性重置凭证
# ══════════════════════════════════════════════════════════════════
def verify_password_reset_code(
    db: OrmSession, cfg: Dict[str, Any], *, username_raw: Any, code_raw: Any
) -> Dict[str, Any]:
    """PR-02：校验验证码。成功 ⇒ **立即消费该码** 并签发一次性 ``reset_token``。

    失败与「账号不存在」**文案与状态码完全一致**（``422`` ＋ 唯一中性文案），
    且账号不存在时同样付等价 HMAC 开销。
    """
    pepper = require_pepper(cfg.get("PASSWORD_RESET_PEPPER"))
    username = normalize_username(username_raw)
    code = "" if code_raw is None else str(code_raw).strip()
    now = now_local()

    account = _get_account(db, username)
    if account is None:
        _equal_cost_probe(pepper, 0)
        raise _invalid_code_error()

    user_id = int(account.id)

    # 取该账号该用途「当前唯一未消费」的挑战码
    challenge = db.execute(
        select(VerificationCode)
        .where(
            VerificationCode.user_id == user_id,
            VerificationCode.purpose == PURPOSE_PASSWORD_RESET,
            VerificationCode.consumed_at.is_(None),
        )
        .order_by(VerificationCode.id.desc())
        .limit(1)
    ).scalars().first()

    if challenge is None:
        # 从未申请 / 已消费 / 已被新码作废
        _equal_cost_probe(pepper, user_id)
        raise _invalid_code_error()

    if challenge.expires_at <= now:
        # 已过期（同样不写库，与"从未申请"不可区分）
        _equal_cost_probe(pepper, user_id)
        raise _invalid_code_error()

    # 防御：历史数据里已达上限的码（正常路径下不会出现）
    if int(challenge.attempt_count) >= CODE_MAX_ATTEMPTS:
        _consume_outstanding_codes(db, user_id, now)
        db.commit()
        raise ApiError(ErrorCode.SESSION_VERIFY_ABORTED)

    matched = verify_verification_code(
        pepper, user_id, PURPOSE_PASSWORD_RESET, code, challenge.code_hash
    )
    if not matched:
        challenge.attempt_count = int(challenge.attempt_count) + 1
        if int(challenge.attempt_count) >= CODE_MAX_ATTEMPTS:
            # 达上限 ⇒ 该码作废，必须重新申请
            _consume_outstanding_codes(db, user_id, now)
            db.commit()
            raise ApiError(ErrorCode.SESSION_VERIFY_ABORTED)
        db.commit()
        raise _invalid_code_error()

    # ── 成功：消费该码 ＋ 作废物化中的其它码/凭证 ＋ 签发一次性 reset token ──
    _consume_outstanding_codes(db, user_id, now)
    revoke_outstanding_reset_tokens(db, user_id, now)

    raw_token = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
            consumed_at=None,
            revoked_at=None,
            created_at=now,
        )
    )
    db.commit()

    return {
        "message": VERIFY_OK_MESSAGE,
        "data": {
            "reset_token": raw_token,
            "expires_in": int(RESET_TOKEN_TTL_MINUTES) * 60,
        },
    }


# ══════════════════════════════════════════════════════════════════
# PR-03 使用重置凭证设置新密码
# ══════════════════════════════════════════════════════════════════
def confirm_password_reset(
    db: OrmSession,
    cfg: Dict[str, Any],
    *,
    reset_token_raw: Any,
    new_password_raw: Any,
    confirm_password_raw: Any,
) -> Dict[str, Any]:
    """PR-03：用 ``reset_token`` 设置新密码。

    校验顺序（**顺序即安全**）：① 凭证命中 → ② 未消费 → ③ 未作废 → ④ 未过期
    → ⑤ 新密码规则（复用 :func:`check_password_rule`）→ ⑥ 两次一致
    → ⑦ 不得与当前密码相同。

    成功后（同一事务）：消费该凭证 → 作废该账号其余未消费凭证 → 作废该账号
    未消费验证码 → **撤销该账号全部会话（``revoked_reason='password_reset'``）**
    → **清零该账号登录失败 / 锁定状态**（``Q-B3-10``，B3 授权 §六）。
    """
    raw = "" if reset_token_raw is None else str(reset_token_raw)
    now = now_local()

    if not raw:
        raise _reset_credential_invalid()

    # 行锁：并发两次 confirm 只有一次能成功（与 refresh_tokens 同构）
    token = db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_reset_token(raw))
        .with_for_update()
    ).scalars().first()

    if (
        token is None
        or token.consumed_at is not None
        or token.revoked_at is not None
        or token.expires_at <= now
    ):
        raise _reset_credential_invalid()

    account = db.get(UserAccount, int(token.user_id))
    if account is None:
        raise _reset_credential_invalid()

    # ── 密码规则（**复用既有统一 policy**，不另立一套）──
    new_password = normalize_password(new_password_raw)
    confirm_password = normalize_password(confirm_password_raw)
    errors: List[dict] = []
    err = check_password_rule(new_password_raw, account.username)
    if err:
        errors.append(field_error("new_password", FieldErrorCode.WEAK_PASSWORD, err))
    if new_password != confirm_password:
        errors.append(
            field_error("confirm_password", FieldErrorCode.MISMATCH, "两次输入的密码不一致")
        )
    if not err and verify_password(new_password, account.password_hash):
        errors.append(
            field_error("new_password", FieldErrorCode.SAME_AS_OLD, "新密码不得与原密码相同")
        )
    if errors:
        raise validation_error(errors)

    # ── 落库 ＋ 失效矩阵（全部在**同一事务**内）──
    user_id = int(account.id)
    account.password_hash = hash_password(new_password, int(cfg["BCRYPT_ROUNDS"]))
    account.password_algo = "bcrypt"
    account.updated_at = now

    # ① 作废该账号其余未消费凭证（排除当前这条，它走"消费"语义）
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
            PasswordResetToken.id != int(token.id),
        )
        .execution_options(synchronize_session=False)
        .values(revoked_at=now)
    )
    # ② 当前凭证：**消费**（一次性，不可重放）
    token.consumed_at = now

    # ③ 作废该账号未消费验证码
    _consume_outstanding_codes(db, user_id, now)

    # ④ 撤销该账号全部会话（reason=password_reset）
    from app.services import auth_service

    revoked = auth_service._revoke_all_sessions(db, user_id, REASON_PASSWORD_RESET)

    # ⑤ Q-B3-10（B3 授权 §六 / §八.25 · 2026-09-24）：清零该账号**登录失败 / 锁定**状态。
    #    · **复用**登录成功分支的既有清零语义（``auth_service._reset_failure_state``）——
    #      否则用户「重置成功却仍被 423 ACCOUNT_LOCKED 挡住」，自助找回实际不可用；
    #    · **最小实现**：无失败状态行则**不创建**（不污染 ``login_failure_state``）；
    #    · **不改变**正常登录失败计数与锁定档位机制（``login_user`` 一字未动）。
    failure_state = auth_service._get_failure_state(db, account.username, create=False)
    if failure_state is not None:
        auth_service._reset_failure_state(failure_state)

    db.commit()

    logger.info(
        "password_reset_confirmed request 结果=OK revoked_sessions=%d（不含任何账号标识）",
        revoked,
    )
    return {
        "message": CONFIRM_OK_MESSAGE,
        "data": {"all_sessions_revoked": True, "revoked_sessions": int(revoked)},
    }


__all__ = [
    "REQUEST_MESSAGE",
    "VERIFY_OK_MESSAGE",
    "INVALID_CODE_MESSAGE",
    "CONFIRM_OK_MESSAGE",
    "RESET_CREDENTIAL_INVALID_MESSAGE",
    "REASON_PASSWORD_RESET",
    "unimplemented_rate_limits",
    "request_password_reset",
    "verify_password_reset_code",
    "confirm_password_reset",
    "revoke_outstanding_reset_tokens",
]
