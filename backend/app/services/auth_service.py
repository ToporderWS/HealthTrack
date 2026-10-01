# -*- coding: utf-8 -*-
"""认证与账号基础模块 —— 服务层。

依据（全部为已封板冻结口径）：
- 《S1-A 安全规则冻结清单》§1 密码强度 / §2 登录失败锁定 / §3 修改密码 / §8 Token 有效期
- 《S1-B 数据库设计文档》§6.2 / §6.3 / §6.7 / §6.8 与 **§7.4 登录失败锁定算法（字段级口径）**
- 《S1-B 第二批 API 接口设计文档》§五 A-01 ~ A-06
- 《S1-D 技术方案最终冻结》§6.1 / §6.2

本模块**只使用**已冻结的 4 张表：``user_account`` / ``user_profile`` / ``user_session`` /
``login_failure_state``；**不新增任何表、字段、索引、错误码**。

事务约定：服务层**自行 commit**；凡「需要持久化后再抛错」的路径（失败计数、锁定状态）
**必须先 commit 再 raise**，否则请求结束时的回滚会丢弃计数。
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.errors import (
    ApiError,
    ErrorCode,
    FieldErrorCode,
    field_error,
    validation_error,
)
from app.core.security import (
    check_password_rule,
    check_username_rule,
    create_access_token,
    dummy_verify,
    format_dt,
    generate_access_token_id,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    normalize_password,
    normalize_username,
    now_local,
    verify_password,
)
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession

# ── `user_session.revoked_reason` 取值（S1-B §6.7 冻结枚举）──────────────
REASON_LOGOUT = "logout"
REASON_PASSWORD_CHANGED = "password_changed"
REASON_TOKEN_REUSE = "token_reuse"
#: **B2 新增第 4 值**（CR-F006-001 · 需求方 B2 授权 §七.13）：找回密码重置成功后
#: 撤销该账号全部会话。不得顺手增加其他 reason。
REASON_PASSWORD_RESET = "password_reset"
# 注：刷新「轮换」失效的旧会话按 S1-D §6.1 冻结表述**只置 `revoked_at`**，
#     `revoked_reason` 留 NULL —— **不新增冻结枚举之外的取值**（详见完成报告"实现解读"）。

#: 一次锁定窗口（24 小时，S1-A §2 冻结）
LOCK_WINDOW_HOURS = 24

#: `user_profile` 中「至少填写一项」参与判定的字段（F-009 建档引导判定口径）
PROFILE_FIELDS: Tuple[str, ...] = (
    "nickname",
    "gender",
    "birth_date",
    "height_cm",
    "initial_weight_kg",
    "blood_type",
    "medical_history",
    "allergy_history",
    "medication_notes",
)


# ════════════════════════════════════════════════════════════════════
# 内部工具
# ════════════════════════════════════════════════════════════════════
def _lock_minutes(cfg: Dict[str, Any], level: int) -> int:
    """锁定档位 → 分钟数（1→5 / 2→15 / 3→60，上限 60）。"""
    table = {
        1: int(cfg["LOGIN_LOCK_MINUTES"]),
        2: int(cfg["LOGIN_LOCK_STEP_1_MINUTES"]),
        3: int(cfg["LOGIN_LOCK_STEP_2_MINUTES"]),
    }
    return table.get(level, table[3])


def _get_account(db: OrmSession, username: str) -> Optional[UserAccount]:
    """按用户名（小写）取账号 —— 走唯一索引 `uk_user_account_username`。"""
    return db.execute(
        select(UserAccount).where(UserAccount.username == username)
    ).scalars().first()


def _get_failure_state(
    db: OrmSession, username: str, create: bool = False
) -> Optional[LoginFailureState]:
    """按用户名取失败状态 —— 走唯一索引 `uk_login_fail_username`。

    ``create=True`` 时若无记录则新建（**覆盖"账号不存在"场景，防账号枚举**）。
    """
    state = db.execute(
        select(LoginFailureState).where(LoginFailureState.username == username)
    ).scalars().first()
    if state is None and create:
        now = now_local()
        state = LoginFailureState(
            username=username,
            fail_count=0,
            first_fail_at=None,
            locked_until=None,
            lock_level=0,
            updated_at=now,
        )
        db.add(state)
    return state


def is_profile_initialized(db: OrmSession, user_id: int) -> bool:
    """档案是否已存在**且至少填写一项**（F-009 建档引导判定的服务端依据）。"""
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if profile is None:
        return False
    return any(getattr(profile, field) is not None for field in PROFILE_FIELDS)


def _issue_session(db: OrmSession, user_id: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """新建一条会话并签发 Access / Refresh（**只 flush，不 commit**）。

    - Access：JWT HS256（2h），``jti`` 落 ``user_session.access_token_id``
    - Refresh：不透明随机串（≥256 bit），**DB 只存 SHA-256 哈希**
    """
    now = now_local()
    access_minutes = int(cfg["TOKEN_ACCESS_MINUTES"])
    refresh_days = int(cfg["TOKEN_REFRESH_DAYS"])

    jti = generate_access_token_id()
    access_token, access_expires_at = create_access_token(
        user_id, jti, cfg.get("SECRET_KEY") or "", access_minutes
    )
    refresh_token = generate_refresh_token()
    refresh_expires_at = now + timedelta(days=refresh_days)

    db.add(
        UserSession(
            user_id=int(user_id),
            refresh_token_hash=hash_refresh_token(refresh_token),
            access_token_id=jti,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            revoked_at=None,
            revoked_reason=None,
            created_at=now,
            last_used_at=now,
        )
    )
    db.flush()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "access_token_expires_in": access_minutes * 60,
        "refresh_token_expires_in": refresh_days * 24 * 3600,
    }


def _revoke_all_sessions(
    db: OrmSession, user_id: int, reason: Optional[str]
) -> int:
    """按 ``user_id`` 批量失效全部会话（走索引 `idx_session_user`）。

    用于：**修改密码**（``password_changed``）与 **Refresh 重放**
    （``token_reuse``）。只置 ``revoked_at``，**不删除数据**。
    """
    now = now_local()
    rows = db.execute(
        select(UserSession).where(
            UserSession.user_id == int(user_id),
            UserSession.revoked_at.is_(None),
        )
    ).scalars().all()
    for row in rows:
        row.revoked_at = now
        row.revoked_reason = reason
    return len(rows)


def _reset_failure_state(state: LoginFailureState) -> None:
    """登录成功后的清零（S1-B §7.4 步骤 4 成功分支）。"""
    state.fail_count = 0
    state.first_fail_at = None
    state.lock_level = 0
    state.locked_until = None
    state.updated_at = now_local()


def _public_user(user: UserAccount) -> Dict[str, Any]:
    """对外用户对象：**只含** `user_id` / `username` / `created_at`。

    **绝不返回** `password_hash` / `password_algo` / `role` / Token / 内部计数。
    """
    return {
        "user_id": int(user.id),
        "username": user.username,
        "created_at": format_dt(user.created_at),
    }


# ════════════════════════════════════════════════════════════════════
# A-01 注册
# ════════════════════════════════════════════════════════════════════
def register_user(
    db: OrmSession,
    cfg: Dict[str, Any],
    *,
    username_raw: Any,
    password_raw: Any,
    agreement_version_raw: Any,
    agreement_accepted: bool,
    auto_login: bool = True,
) -> Dict[str, Any]:
    """F-001 / F-008 / F-076：注册（用户名 + 密码）。"""
    username = normalize_username(username_raw)
    password = normalize_password(password_raw)

    # ── 语义校验（→ 422 VALIDATION_FAILED，附字段级明细）──
    errors: List[dict] = []
    err = check_username_rule(username_raw)
    if err:
        errors.append(field_error("username", FieldErrorCode.INVALID_FORMAT, err))
    err = check_password_rule(password_raw, username)
    if err:
        errors.append(field_error("password", FieldErrorCode.WEAK_PASSWORD, err))
    if not agreement_version_raw or not str(agreement_version_raw).strip():
        errors.append(
            field_error("agreement_version", FieldErrorCode.INVALID_FORMAT, "协议版本不能为空")
        )
    if agreement_accepted is not True:
        errors.append(
            field_error(
                "agreement_accepted", FieldErrorCode.NOT_ACCEPTED, "请先阅读并同意用户协议与隐私政策"
            )
        )
    if errors:
        raise validation_error(errors)

    # ── 用户名占用（F-001 冻结口径：注册**必须**明确告知占用）──
    if _get_account(db, username) is not None:
        raise ApiError(ErrorCode.USERNAME_TAKEN)

    now = now_local()
    account = UserAccount(
        username=username,
        password_hash=hash_password(password, int(cfg["BCRYPT_ROUNDS"])),
        password_algo="bcrypt",
        role="user",
        # 协议同意**服务端留痕**（F-008：不能只靠前端标记）
        terms_agreed_at=now,
        agreement_version=str(agreement_version_raw).strip(),
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError:
        # 并发注册同一用户名：唯一索引兜底
        db.rollback()
        raise ApiError(ErrorCode.USERNAME_TAKEN)

    data: Dict[str, Any] = {"user": _public_user(account)}
    data["tokens"] = _issue_session(db, int(account.id), cfg) if auto_login else None
    db.commit()
    return data


# ════════════════════════════════════════════════════════════════════
# A-02 登录（含失败锁定）
# ════════════════════════════════════════════════════════════════════
def login_user(
    db: OrmSession,
    cfg: Dict[str, Any],
    *,
    username_raw: Any,
    password_raw: Any,
) -> Dict[str, Any]:
    """F-002 / F-077：登录。

    实现严格遵循 S1-B §7.4 的**四步顺序**：
    ``读状态 → 判锁定 → 过期则清零 → 校验凭据``。

    ⚠️ 防账号枚举：失败文案、锁定文案对「账号存在 / 不存在」**完全一致**；
    ``login_failure_state`` 对不存在的用户名**同样落行**。
    """
    username = normalize_username(username_raw)
    password = normalize_password(password_raw)
    now = now_local()

    state = _get_failure_state(db, username, create=False)

    # ── 步骤 2：锁定期内直接拒绝（**先判锁定，再校验凭据**）──
    if state is not None and state.locked_until is not None and state.locked_until > now:
        left = max(1, math.ceil((state.locked_until - now).total_seconds() / 60.0))
        raise ApiError(
            ErrorCode.ACCOUNT_LOCKED,
            message=f"账号已临时锁定，请 {left} 分钟后再试",
            data={"locked_minutes": left},
        )

    # ── 步骤 3：锁定已到期 → 计数清零（24h 窗口内保留锁定档位以支持递增）──
    if state is not None and state.locked_until is not None and state.locked_until <= now:
        state.fail_count = 0
        state.locked_until = None
        if state.first_fail_at is None or (
            now - state.first_fail_at
        ) > timedelta(hours=LOCK_WINDOW_HOURS):
            state.first_fail_at = None
            state.lock_level = 0
        state.updated_at = now

    # ── 步骤 4：校验凭据 ──
    account = _get_account(db, username)
    if account is None:
        # 对不存在的用户名做等量哈希开销，避免时序侧信道区分账号是否存在
        dummy_verify(password)
        ok = False
    else:
        ok = verify_password(password, account.password_hash)

    if ok:
        if state is not None:
            _reset_failure_state(state)
        tokens = _issue_session(db, int(account.id), cfg)
        db.commit()
        return {
            "user": {"user_id": int(account.id), "username": account.username},
            "profile_initialized": is_profile_initialized(db, int(account.id)),
            "tokens": tokens,
        }

    # ── 失败分支：计数 +1（**对不存在的用户名同样落行**）──
    if state is None:
        state = _get_failure_state(db, username, create=True)
    state.fail_count = int(state.fail_count) + 1
    state.updated_at = now

    max_fails = int(cfg["LOGIN_MAX_FAILS"])
    if state.fail_count < max_fails:
        db.commit()
        raise ApiError(ErrorCode.CREDENTIALS_INVALID)

    # 达到阈值 → 触发锁定（档位在 24h 窗口内递增，上限第 3 档 = 60 分钟）
    if state.first_fail_at is None or (
        now - state.first_fail_at
    ) > timedelta(hours=LOCK_WINDOW_HOURS):
        state.first_fail_at = now
        level = 1
    elif int(state.lock_level) <= 1:
        level = 2
    else:
        level = 3
    minutes = _lock_minutes(cfg, level)
    state.lock_level = level
    state.locked_until = now + timedelta(minutes=minutes)
    state.fail_count = 0  # 触发锁定后计数归零（§7.4）
    db.commit()
    raise ApiError(
        ErrorCode.ACCOUNT_LOCKED,
        message=f"账号已临时锁定，请 {minutes} 分钟后再试",
        data={"locked_minutes": minutes},
    )


# ════════════════════════════════════════════════════════════════════
# A-03 刷新 Token
# ════════════════════════════════════════════════════════════════════
def refresh_tokens(
    db: OrmSession, cfg: Dict[str, Any], *, refresh_token_raw: Any
) -> Dict[str, Any]:
    """F-077：刷新访问令牌（**刷新令牌单次使用 + 轮换 + 防重放**）。"""
    raw = "" if refresh_token_raw is None else str(refresh_token_raw)
    if not raw:
        raise ApiError(ErrorCode.INVALID_PARAM)

    # 走唯一索引 uk_session_refresh；加行锁保证「单次使用」在并发下依然成立
    session = db.execute(
        select(UserSession)
        .where(UserSession.refresh_token_hash == hash_refresh_token(raw))
        .with_for_update()
    ).scalars().first()
    if session is None:
        raise ApiError(ErrorCode.UNAUTHENTICATED)

    now = now_local()

    # ── 重放检测：令牌命中但会话已失效 → 认定重放，**该用户全部会话立即失效** ──
    if session.revoked_at is not None:
        _revoke_all_sessions(db, int(session.user_id), REASON_TOKEN_REUSE)
        db.commit()
        raise ApiError(ErrorCode.TOKEN_REUSED)

    if session.refresh_expires_at <= now:
        raise ApiError(ErrorCode.UNAUTHENTICATED)

    # ── 轮换：旧会话置 revoked_at（S1-D §6.1「旧的置 revoked_at，签发新的」）──
    session.revoked_at = now
    session.revoked_reason = None
    tokens = _issue_session(db, int(session.user_id), cfg)
    db.commit()
    return tokens


# ════════════════════════════════════════════════════════════════════
# A-04 退出登录
# ════════════════════════════════════════════════════════════════════
def logout_session(db: OrmSession, session: UserSession) -> None:
    """F-003 / F-077：**仅失效当前会话**（不影响其他设备）。"""
    if session.revoked_at is None:
        session.revoked_at = now_local()
        session.revoked_reason = REASON_LOGOUT
        db.commit()


# ════════════════════════════════════════════════════════════════════
# A-05 修改密码
# ════════════════════════════════════════════════════════════════════
def change_password(
    db: OrmSession,
    cfg: Dict[str, Any],
    *,
    account: UserAccount,
    session: UserSession,
    old_password_raw: Any,
    new_password_raw: Any,
    confirm_password_raw: Any,
) -> Dict[str, Any]:
    """F-004 / F-076 / F-077：修改密码。

    冻结口径：
    ① 原密码**在服务端**校验；
    ② 原密码**同一会话连错 5 次** → ``429 SESSION_VERIFY_ABORTED``
       （**不锁定账号、不计入登录失败计数**，计数存 ``user_session.change_pwd_fail_count``）；
    ③ 成功后该账号**全部旧 Token 立即失效**（含当前设备）。
    """
    old_password = normalize_password(old_password_raw)
    new_password = normalize_password(new_password_raw)
    confirm_password = normalize_password(confirm_password_raw)

    # ── ① 原密码校验（服务端唯一权威）──
    if not verify_password(old_password, account.password_hash):
        session.change_pwd_fail_count = int(session.change_pwd_fail_count) + 1
        limit = int(cfg["VERIFY_MAX_PASSWORD_CHANGE"])
        if session.change_pwd_fail_count >= limit:
            db.commit()
            raise ApiError(ErrorCode.SESSION_VERIFY_ABORTED)
        db.commit()
        raise ApiError(ErrorCode.PASSWORD_INVALID)

    # ── ② 新密码规则（沿用 S1-A §1 密码强度）──
    errors: List[dict] = []
    err = check_password_rule(new_password_raw, account.username)
    if err:
        errors.append(field_error("new_password", FieldErrorCode.WEAK_PASSWORD, err))
    if new_password != confirm_password:
        errors.append(
            field_error("confirm_password", FieldErrorCode.MISMATCH, "两次输入的密码不一致")
        )
    if not err and new_password == old_password:
        errors.append(
            field_error("new_password", FieldErrorCode.SAME_AS_OLD, "新密码不得与原密码相同")
        )
    if errors:
        raise validation_error(errors)

    # ── ③ 落库 + 该用户全部会话失效 ──
    now = now_local()
    account.password_hash = hash_password(new_password, int(cfg["BCRYPT_ROUNDS"]))
    account.password_algo = "bcrypt"
    account.updated_at = now
    revoked = _revoke_all_sessions(db, int(account.id), REASON_PASSWORD_CHANGED)

    # ── E-24（CR-F006-001 · B2 授权 §八）：改密成功 ⇒ 作废该账号**未消费**的重置凭证 ──
    #    闭合「用户刚主动改密，此前签发的 reset token 在剩余 15 分钟内仍能再改一次密码」的窗口。
    #    只写 revoked_at（与用户真实消费过的 consumed_at 语义互斥可辨，见 models/password_reset_token.py）。
    #    ⚠️ 最小改动：A-05 的原密码校验 / password policy / bcrypt / Session revoke / 响应契约全部不变。
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == int(account.id),
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
        )
        .execution_options(synchronize_session=False)
        .values(revoked_at=now)
    )
    db.commit()
    return {"all_sessions_revoked": True, "revoked_sessions": revoked}


# ════════════════════════════════════════════════════════════════════
# A-06 当前用户
# ════════════════════════════════════════════════════════════════════
#: 掩码保留的 local-part 首字符数（固定 1，与 local-part 长度无关 ⇒ 不泄露长度）
MASK_LOCAL_KEEP = 1
#: 掩码占位串（**固定** ``***``，不随真实长度伸缩 ⇒ 无长度侧信道）
MASK_FILL = "***"


def mask_email(email: Optional[str]) -> Optional[str]:
    """把**已验证**邮箱转为安全掩码展示值（**仅用于展示**，不改变库中真实邮箱）。

    冻结规则（B4-PRE-01 §二）：①不泄露完整邮箱；②保留域名供用户识别；
    ③对合法邮箱**确定性**输出；④短 local-part 不越界；⑤不改库；⑥仅供展示。

    形态：``local[:1] + "***" + "@" + domain``（在**最后一个** ``@`` 处切分）。
    ``None`` / 空串 / 非法（无 ``@`` / local 为空 / domain 为空 / local 内仍含 ``@``）
    一律返回 ``None`` —— 宁可无值，也不回显可疑原值。
    """
    if not email:
        return None
    text = str(email)
    local, sep, domain = text.rpartition("@")
    if not sep or not local or not domain or "@" in local:
        return None
    return "%s%s@%s" % (local[:MASK_LOCAL_KEEP], MASK_FILL, domain)


def build_current_user(db: OrmSession, account: UserAccount) -> Dict[str, Any]:
    """F-064 / F-078：只读 ``username`` / ``created_at``（**user_id 只来自 Token**）。

    B4-PRE-01（**add-only**）：追加 ``email_bound`` / ``email_masked`` —— 只读当前账号
    **已经存在**的绑定结果；不重设计绑定机制、不改 B2/B3 任何行为。

    - ``email_bound`` 仅当 ``email`` 与 ``email_verified_at`` **同时非空**才为 ``True``
      （显式 AND，**不依赖** DB ``ck_user_account_email_pair`` 兜底）；
    - 未绑定时 ``email_masked`` 恒为 ``None``；
    - **不返回** ``email`` 明文 / ``email_verified_at`` / 任何其他 PII。
    """
    email = getattr(account, "email", None)
    verified_at = getattr(account, "email_verified_at", None)
    email_bound = bool(email) and verified_at is not None
    return {
        "user_id": int(account.id),
        "username": account.username,
        "created_at": format_dt(account.created_at),
        "profile_initialized": is_profile_initialized(db, int(account.id)),
        "email_bound": email_bound,
        "email_masked": mask_email(email) if email_bound else None,
    }


__all__ = [
    "register_user",
    "login_user",
    "refresh_tokens",
    "logout_session",
    "change_password",
    "build_current_user",
    "is_profile_initialized",
    "mask_email",
]
