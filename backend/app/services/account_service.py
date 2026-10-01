# -*- coding: utf-8 -*-
"""账号服务（本批实现 **A-07 注销账号**）。

依据（**逐条落实，不发明规则**）：
- 《S1-B 第二批 API 接口设计文档》§五 A-07（679~727 行）
- 《S1-B 第二批 API 接口设计文档》§十五 15.4 / 15.6（2055~2088 行，R-13 核心 + 日志约束）
- 《S1-B 数据库设计文档》§13.3 / §13.4 / §13.6 / §13.7（1006~1096 行）

冻结口径：
- **A-07 与 D-02 严格区分**：D-02 = 清数据、**保留账号**、软删；A-07 = **注销账号**、
  **物理删除（含已软删行）**、**30 天规则绝不适用**。
- **T0 三重确认**：有效登录态（``user_id`` 由 Token 解析）+ **密码验证** + **确认文字「注销账号」**；
  契约**不含** ``acknowledge_irreversible``（不得从 D-02 复制该参数）。
- **T2 级联物理删除（顺序冻结，接口层不得调整）**：见 :data:`DELETE_ORDER`；
  **不得读取 `deleted_at` 做 30 天判断** —— ``is_deleted`` 取 0 或 1 **一律物理删除**。
- **单事务**：任一步失败 → 整体回滚 → ``500 INTERNAL_ERROR``（**不得产生"半注销"**）。
- **C7 完整性自检**：数据库 0 外键 ⇒ 服务层承担完整性责任；**提交前**必须复查 10 张表
  目标数据均归零，否则抛异常并回滚。
  （**B2 起为 10 张**：新增 ``verification_code`` / ``password_reset_token``。）
- **T4 事务外文件处置**：**commit 之后**才删除导出文件；失败**不得 rollback**、**仍返回 200**；
  写**脱敏**日志（不含 ``user_id`` / 用户名 / 完整 ``file_path``）并**登记重试**。
- **幂等**：账号已删除 → 携带的 Token 必然失效 → ``401``（``core/auth.py`` 天然实现，无需特殊逻辑）。
- **越权边界**：``user_id`` 只能来自 Access Token；拒绝任何范围扩展参数
  （``grace_period`` / ``defer`` / ``schedule`` / ``target_user_id`` 等契约未定义项）。

★ **关于 T4「重试」的落地口径（C6，Step 1 前已获用户确认）**：
本系统 V1.0 **没有后台 worker / 定时任务基础设施**（见实现报告"未做事项"）。
因此本模块实现**当前能力边界下的最小符合契约的重试机制**：
① 删除失败的文件以**文件名**登记到 ``storage/cleanup_retry.jsonl``（**不入业务库、不新增表/迁移**）；
② :func:`drain_cleanup_retries` 为**真实可执行的**重放函数，由下一次注销流程**顺带调用**
   （opportunistic drain）；重放仍失败则 ``attempt + 1`` 保留登记；
③ 真正的"后台自动执行（定时调度）"能力**登记为后续基础设施项**——本模块**不伪造**后台任务。

★ **S4-2 头像窄扩展（2026-09-22 授权 · 唯一 2 处，各 1 小段）**：
头像实体文件必须随注销一并清理（避免孤儿文件）。为**不动历史封板语义**，此处只做两件事：
① **删除 `user_profile` 行之前**多取一列 ``avatar_key``（**与既有「删 `export_job` 之前先取
   `file_path`」完全同构**）；② **`commit` 之后**调用 :func:`avatar_service.cleanup_avatar_files`。
**未改动**：8 步 :data:`DELETE_ORDER` 顺序 / :func:`_assert_no_residue` 语义 /
单事务 + ``rollback`` 主流程 / T5 日志字段 / 导出清理队列格式与逻辑。
头像清理失败**不回滚、不影响注销结果**，重试登记走**独立** ``avatar_cleanup_retry.jsonl``
（**不可复用** :func:`drain_cleanup_retries` —— 其唯一解析根是 ``EXPORT_DIR``）。
**历史 A-07 = SEALED 结论保持不变。**

★ **B2 窄扩展（2026-09-24 授权 · ``DELETE_ORDER`` 8 → 10）**：
``CR-F006-001`` 引入 ``verification_code`` / ``password_reset_token`` 两张安全数据表 ⇒
注销必须能清理它们（否则注销后残留邮箱 / 验证码 / 重置凭证 ⇒ 隐私与安全双风险）。
按授权 §九 **只加入这两张表**，原 6 张顺序**一字未动**，``user_account`` 仍在**最后**；
项目 **0 外键** ⇒ **不虚构 FK**、不加级联（两张新表同样以 ``user_id`` 逻辑关联）。
**未改动**：T0 三重确认 / 单事务 ＋ ``rollback`` 主流程 / 事务外文件与头像处置 /
T5 日志字段 / 清理重试队列逻辑。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    ApiError,
    ErrorCode,
    FieldErrorCode,
    field_error,
    validation_error,
)
from app.core.security import normalize_password, now_local, verify_password
from app.models.export_job import ExportJob
from app.models.health_goal import HealthGoal
from app.models.health_record import HealthRecord
from app.models.login_failure_state import LoginFailureState
from app.models.password_reset_token import PasswordResetToken
from app.models.record_tag import RecordTag
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.models.user_session import UserSession
from app.models.verification_code import VerificationCode
from app.services import avatar_service, export_service

logger = logging.getLogger(__name__)

#: A-07 确认文字 —— **独立常量**（冻结「注销账号」；**不得**复用 D-02 的「确认删除」）
CONFIRM_TEXT = "注销账号"

#: A-07 成功文案（冻结；**与"退出登录"文案严格区分**）
CLOSED_MESSAGE = "账号已注销"

#: 成功响应 ``data`` **恰 1 键**（冻结；不增加删除条数 / warning / soft_warning）
CLOSED_DATA: Dict[str, Any] = {"account_closed": True}

#: T2 级联物理删除的**固定顺序**（契约冻结，不得调整；**账号最后**）
DELETE_ORDER: Tuple[str, ...] = (
    "record_tag",
    "health_record",
    "health_goal",
    "user_profile",
    "export_job",
    "user_session",
    "login_failure_state",
    # ── B2 扩展（CR-F006-001 · 授权 §九）：新增 2 张安全数据表，仍保持「账号最后」──
    "verification_code",
    "password_reset_token",
    "user_account",
)

#: 重试登记队列文件名（落盘于 ``backend/storage/`` 根；**不入业务库**）
CLEANUP_RETRY_FILENAME = "cleanup_retry.jsonl"

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 表名 → ORM 模型（用于 8 步删除与残留自检）
_MODEL_OF = {
    "record_tag": RecordTag,
    "health_record": HealthRecord,
    "health_goal": HealthGoal,
    "user_profile": UserProfile,
    "export_job": ExportJob,
    "user_session": UserSession,
    "login_failure_state": LoginFailureState,
    "verification_code": VerificationCode,
    "password_reset_token": PasswordResetToken,
    "user_account": UserAccount,
}


# ════════════════════════════════════════════════════════════════════
# 内部工具
# ════════════════════════════════════════════════════════════════════
def _rid() -> str:
    from app.core.request_id import get_request_id

    return get_request_id()


def _export_base_real() -> str:
    """``EXPORT_DIR`` 的规范化真实路径（文件处置的**唯一合法根**）。"""
    base = export_service.export_dir()
    if not base:
        raise OSError("EXPORT_DIR 未配置")
    return os.path.realpath(base)


def retry_queue_path() -> str:
    """重试登记文件路径（与 ``EXPORT_DIR`` **同级**的 storage 根；不写入业务库）。"""
    return os.path.join(os.path.dirname(_export_base_real()), CLEANUP_RETRY_FILENAME)


def _safe_export_target(stored: Any) -> Optional[str]:
    """把库内 ``file_path`` 收敛为**必须位于 ``EXPORT_DIR`` 内**的真实路径。

    防目录穿越：越界 / 不同盘符 → ``None``（拒绝删除，**绝不删除 EXPORT_DIR 之外的文件**）。
    """
    if not stored:
        return None
    base_real = _export_base_real()
    target = os.path.realpath(str(stored))
    try:
        inside = os.path.commonpath([base_real, target]) == base_real
    except ValueError:  # 混合绝对/相对路径、不同盘符
        inside = False
    return target if inside else None


def _unlink(path: str) -> None:
    """**实际删除文件的原语**（本模块唯一删除入口；便于测试注入失败以验证 T4 分支）。"""
    os.remove(path)


def _remove_export_file(stored: Any) -> None:
    """删除一个导出文件；越界 → 抛 ``ValueError``；文件已不存在 → 幂等成功。"""
    target = _safe_export_target(stored)
    if target is None:
        raise ValueError("导出文件路径越界")
    if not os.path.isfile(target):
        return                      # 已不存在 ⇒ 视为已清理（幂等）
    _unlink(target)


# ════════════════════════════════════════════════════════════════════
# T4 重试登记队列（当前系统支持的最小重试机制）
# ════════════════════════════════════════════════════════════════════
def _read_retry_queue() -> List[Dict[str, Any]]:
    path = retry_queue_path()
    if not os.path.isfile(path):
        return []
    items: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    entry = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("file_name"):
                    items.append(entry)
    except OSError:
        logger.warning("重试登记队列读取失败（code=OSError）")
        return []
    return items


def _write_retry_queue(items: Sequence[Dict[str, Any]]) -> None:
    path = retry_queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in items:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def enqueue_cleanup_retry(file_name: str, code: str,
                          job_id: Optional[int] = None,
                          attempt: int = 1) -> None:
    """登记一条待重试的导出文件清理项。

    **只记录文件名**（``basename``）——不记录 ``user_id``、用户名、完整 ``file_path``，
    满足 15.6 / 13.3.3 的脱敏约束。
    """
    name = os.path.basename(str(file_name or ""))
    if not name:
        return
    path = retry_queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {
        "file_name": name,
        "attempt": int(attempt),
        "code": str(code),
        "job_id": job_id,
        "ts": now_local().strftime(DATETIME_FORMAT),
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def drain_cleanup_retries() -> Tuple[int, int]:
    """重放已登记的待清理导出文件（**真实可执行**的最小重试机制）。

    - 逐条尝试删除 ``EXPORT_DIR / <file_name>``；成功或文件已不存在 → 移出队列；
    - 仍失败 → ``attempt + 1`` 保留登记，并写**脱敏**告警日志；
    - **无后台 worker/定时任务** ⇒ 由下一次注销流程**顺带调用**本函数；
      真正的"后台自动执行"能力属**后续基础设施项**（本模块不伪造后台任务）。

    返回 ``(cleared, remaining)``。
    """
    items = _read_retry_queue()
    if not items:
        return 0, 0

    base_real = _export_base_real()
    remaining: List[Dict[str, Any]] = []
    cleared = 0
    for entry in items:
        name = os.path.basename(str(entry.get("file_name") or ""))
        if not name:
            continue
        target = os.path.join(base_real, name)
        try:
            if os.path.isfile(target):
                _unlink(target)
            cleared += 1
        except OSError as exc:
            entry["attempt"] = int(entry.get("attempt") or 1) + 1
            entry["code"] = type(exc).__name__
            entry["ts"] = now_local().strftime(DATETIME_FORMAT)
            remaining.append(entry)
            logger.warning(
                "导出文件重试清理失败（attempt=%s code=%s job_id=%s）",
                entry["attempt"], entry["code"], entry.get("job_id"),
            )
    _write_retry_queue(remaining)
    return cleared, len(remaining)


def _cleanup_export_files(targets: Sequence[Tuple[int, Any]]) -> Tuple[int, int]:
    """T4：**事务提交后**删除导出文件；失败 → 登记重试（**绝不回滚已提交的注销**）。

    - ``OSError``（真删除失败）→ 计数 + **登记重试**（可追踪，由 drain 重放）；
    - ``ValueError``（库内 ``file_path`` **越界**）→ 属数据异常，**安全拒绝删除**
      （``EXPORT_DIR`` 之外的文件不受本系统管辖），只写脱敏告警、**不登记重试**。

    返回 ``(failed, retry_remaining)``。
    """
    failed = 0
    for job_id, stored in targets:
        try:
            _remove_export_file(stored)
        except ValueError:
            logger.warning(
                "导出文件路径越界，已拒绝删除（code=ValueError job_id=%s）", job_id
            )
        except OSError as exc:
            failed += 1
            code = type(exc).__name__
            enqueue_cleanup_retry(os.path.basename(str(stored or "")), code, job_id)
            logger.warning(
                "导出文件清理失败，已登记重试（attempt=1 code=%s job_id=%s）",
                code, job_id,
            )
    _cleared, remaining = drain_cleanup_retries()
    return failed, remaining


# ════════════════════════════════════════════════════════════════════
# T0 三重确认
# ════════════════════════════════════════════════════════════════════
def _validate_confirm(payload: Dict[str, Any]) -> None:
    """确认文字「注销账号」。

    C4 冻结口径：
    - **缺失** → ``422 VALIDATION_FAILED`` + ``REQUIRED``（``field=confirm_text``）；
    - **不正确** → ``422 VALIDATION_FAILED`` + ``INVALID_FORMAT``（``field=confirm_text``）。
    """
    if "confirm_text" not in payload or payload.get("confirm_text") is None:
        raise validation_error([
            field_error("confirm_text", FieldErrorCode.REQUIRED, "确认文字不能为空")
        ])
    text = payload.get("confirm_text")
    if not isinstance(text, str) or text.strip() != CONFIRM_TEXT:
        raise validation_error([
            field_error("confirm_text", FieldErrorCode.INVALID_FORMAT, "确认文字不正确")
        ])


def _verify_login_password(account: UserAccount, payload: Dict[str, Any]) -> None:
    """登录密码验证（**针对当前账户**）。

    冻结口径：密码错误 → ``422 PASSWORD_INVALID``；
    **不累计失败次数、不触发账号锁定、不返回 429**（与登录失败机制无关）。
    """
    raw = payload.get("password")
    if not isinstance(raw, str) or not raw.strip():
        raise validation_error([
            field_error("password", FieldErrorCode.REQUIRED, "密码不能为空")
        ])
    if not verify_password(normalize_password(raw), account.password_hash):
        raise ApiError(ErrorCode.PASSWORD_INVALID)


# ════════════════════════════════════════════════════════════════════
# T2 级联物理删除 + C7 残留自检
# ════════════════════════════════════════════════════════════════════
def _purge(db: Session, model: Any, *criteria: Any) -> int:
    """物理删除（``DELETE``；**不读 `deleted_at`、无 30 天条件**）。返回受影响行数。"""
    result = db.execute(
        delete(model).where(*criteria).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _residue_criteria(user_id: int, username: str) -> Dict[str, Any]:
    """10 张表的目标数据判据（``login_failure_state`` 按 ``username``；其余按 ``user_id`` / ``id``）。"""
    return {
        "record_tag": RecordTag.user_id == int(user_id),
        "health_record": HealthRecord.user_id == int(user_id),
        "health_goal": HealthGoal.user_id == int(user_id),
        "user_profile": UserProfile.user_id == int(user_id),
        "export_job": ExportJob.user_id == int(user_id),
        "user_session": UserSession.user_id == int(user_id),
        "login_failure_state": LoginFailureState.username == str(username),
        "verification_code": VerificationCode.user_id == int(user_id),
        "password_reset_token": PasswordResetToken.user_id == int(user_id),
        "user_account": UserAccount.id == int(user_id),
    }


def _assert_no_residue(db: Session, user_id: int, username: str) -> None:
    """**C7 事务提交前的完整性自检**。

    数据库 **0 外键** ⇒ 服务层承担完整性责任：逐表复查目标数据必须全部归零；
    任一表仍有残留 → 抛异常（外层 rollback）。
    """
    residues: List[Tuple[str, int]] = []
    for table in DELETE_ORDER:
        model = _MODEL_OF[table]
        criteria = _residue_criteria(user_id, username)[table]
        left = int(db.execute(
            select(func.count()).select_from(model).where(criteria)
        ).scalar() or 0)
        if left:
            residues.append((table, left))
    if residues:
        raise RuntimeError(f"注销完整性自检未通过，仍存在残留：{residues!r}")


# ════════════════════════════════════════════════════════════════════
# A-07 主流程
# ════════════════════════════════════════════════════════════════════
def close_account(db: Session, *, user_id: int, account: UserAccount,
                  payload: Dict[str, Any]) -> Dict[str, Any]:
    """A-07：注销当前账号（**单事务物理删除 10 张表 + 事务外文件处置**）。

    顺序严格遵循冻结契约：``T0 校验 → T1 单事务 → T2 8 步物理删除 + 残留自检 →
    T3 commit → T4 事务外删除导出文件（失败仍 200 + 登记重试）→ T5 脱敏日志``。
    """
    if not isinstance(payload, dict):
        raise ApiError(ErrorCode.INVALID_PARAM)

    # ── T0：三重确认（登录态已由 require_auth 保证）──
    _validate_confirm(payload)
    _verify_login_password(account, payload)

    account_id = int(user_id)
    username = str(account.username)

    # ── 删除 ``export_job`` 行**之前**先取出 ``file_path``（契约 T2 第 5 步要求）──
    file_targets: List[Tuple[int, Any]] = [
        (int(job.id), job.file_path)
        for job in db.execute(
            select(ExportJob).where(ExportJob.user_id == account_id)
        ).scalars().all()
        if job.file_path
    ]

    # ── S4-2 窄扩展（2 处之一）：删除 ``user_profile`` 行**之前**先取出 ``avatar_key`` ──
    #    **与上一段「删 `export_job` 之前先取 `file_path`」完全同构**：只多读一列。
    #    8 步 `DELETE_ORDER` 顺序、`_assert_no_residue` 语义、单事务 + rollback 主流程**均不变**。
    avatar_key = db.execute(
        select(UserProfile.avatar_key).where(UserProfile.user_id == account_id)
    ).scalars().first() or None

    # ── T1 + T2 + C7 + T3：单事务 ──
    counts: Dict[str, int] = {}
    try:
        counts["record_tag"] = _purge(db, RecordTag, RecordTag.user_id == account_id)
        counts["health_record"] = _purge(db, HealthRecord, HealthRecord.user_id == account_id)
        counts["health_goal"] = _purge(db, HealthGoal, HealthGoal.user_id == account_id)
        counts["user_profile"] = _purge(db, UserProfile, UserProfile.user_id == account_id)
        counts["export_job"] = _purge(db, ExportJob, ExportJob.user_id == account_id)
        counts["user_session"] = _purge(db, UserSession, UserSession.user_id == account_id)
        counts["login_failure_state"] = _purge(
            db, LoginFailureState, LoginFailureState.username == username
        )
        # ── B2 扩展：两张安全数据表（``user_id`` 逻辑关联；0 外键 ⇒ 显式删除）──
        counts["verification_code"] = _purge(
            db, VerificationCode, VerificationCode.user_id == account_id
        )
        counts["password_reset_token"] = _purge(
            db, PasswordResetToken, PasswordResetToken.user_id == account_id
        )
        counts["user_account"] = _purge(db, UserAccount, UserAccount.id == account_id)

        _assert_no_residue(db, account_id, username)   # C7：只有全部归零才能提交
        db.commit()
    except Exception:
        db.rollback()
        # 脱敏：不写 user_id / 用户名 / 健康数据
        logger.exception("账号注销失败，已整体回滚（request_id=%s）", _rid())
        raise ApiError(ErrorCode.INTERNAL_ERROR)

    # ── T4：事务已提交，事务外处置导出文件（失败**不得**回滚）──
    failed_files, retry_remaining = _cleanup_export_files(file_targets)

    # ── S4-2 窄扩展（2 处之二）：事务外清理**头像实体文件**（避免孤儿）──
    #    同样在 commit **之后**执行；失败**不回滚、不影响注销结果**；
    #    重试登记走**独立** `avatar_cleanup_retry.jsonl`（既有导出清理队列逻辑 0 改动）。
    if avatar_key:
        avatar_service.cleanup_avatar_files([avatar_key])

    # ── T5：运行日志（account_closed + request_id + 结果 + 条数统计；**不含个人标识**）──
    logger.info(
        "account_closed request_id=%s 结果=OK 条数=%s 文件失败=%s 待重试=%s",
        _rid(),
        json.dumps(counts, ensure_ascii=False, sort_keys=True),
        failed_files,
        retry_remaining,
    )
    return dict(CLOSED_DATA)


__all__ = [
    "CLEANUP_RETRY_FILENAME",
    "CLOSED_DATA",
    "CLOSED_MESSAGE",
    "CONFIRM_TEXT",
    "DELETE_ORDER",
    "close_account",
    "drain_cleanup_retries",
    "enqueue_cleanup_retry",
    "retry_queue_path",
]
