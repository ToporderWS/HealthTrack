# -*- coding: utf-8 -*-
"""B1-C：数据模型层（**真实 MySQL 集成**，覆盖需求方 §八 的 1~14 条）。

判据纪律
--------
- 所有期望值**硬编码**在本文件（铁律⑨），不取自被测对象自身的返回值；
- 结构类判据走 ``information_schema``（独立于 ORM）；
- 行为类判据用**绑参** SQL（不拼字符串），且只针对本测试自己写入的 ``tst`` 前缀账号；
- 收尾清理由 ``conftest._pw_scope_guard`` 负责，并断言 10 张表行数逐表还原。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import bindparam, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.db import get_engine, get_session_factory
from app.core.password_reset import (
    CODE_MAX_ATTEMPTS,
    PURPOSE_PASSWORD_RESET,
    hash_reset_token,
    hash_verification_code,
)
from app.core.security import hash_password, now_local
from app.models.password_reset_token import PasswordResetToken
from app.models.user_account import EMAIL_COLLATION, UserAccount
from app.models.verification_code import VerificationCode
from tests.pwreset.conftest import TEST_PREFIX, unique_username

PEPPER = "t" * 32
_AUTO = "\x00AUTO"   # 「按 email 自动决定 email_verified_at」的哨兵

#: 两张新表的列集合（**硬编码冻结**，顺序 = information_schema ORDINAL 顺序）
EXPECT_VCODE_COLS = (
    "id", "user_id", "purpose", "code_hash", "expires_at",
    "consumed_at", "attempt_count", "created_at",
)
EXPECT_PRT_COLS = (
    "id", "user_id", "token_hash", "expires_at",
    "consumed_at", "revoked_at", "created_at",
)
#: 索引：``{名: (唯一性, 列序)}``（1 = 唯一）
EXPECT_VCODE_IDX = {
    "idx_vcode_user_purpose": (0, ("user_id", "purpose", "consumed_at")),
    "idx_vcode_expires": (0, ("expires_at",)),
}
EXPECT_PRT_IDX = {
    "uk_prt_token_hash": (1, ("token_hash",)),
    "idx_prt_user_outstanding": (0, ("user_id", "consumed_at", "revoked_at")),
    "idx_prt_expires": (0, ("expires_at",)),
}
#: 明文列名黑名单（``*_hash`` 之外出现任一即视为「结构上可存明文」）
PLAINTEXT_COL_BLACKLIST = ("code", "token", "verification_code", "reset_token", "secret")


# ══════════════════════════════════════════════════════════════════
# 只读查询助手（**一律绑参**）
# ══════════════════════════════════════════════════════════════════
def rows(sql: str, **params) -> list:
    with get_engine().connect() as conn:
        return list(conn.execute(text(sql), params).fetchall())


def scalar(sql: str, **params):
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params).scalar()


def prefix(tag: str) -> str:
    """本测试专属用户名前缀（用于只统计自己写入的行）。"""
    return f"{TEST_PREFIX}{tag}%"


# ══════════════════════════════════════════════════════════════════
# 写入助手（每次独立会话；约束冲突互不污染）
# ══════════════════════════════════════════════════════════════════
def add_account(email=None, verified_at=_AUTO, username=None) -> int:
    """建测试账号；``verified_at=_AUTO`` ⇒ 有邮箱时自动置 ``now()``。"""
    if verified_at is _AUTO:
        verified_at = now_local() if email is not None else None
    factory = get_session_factory()
    now = now_local()
    with factory() as s:
        acc = UserAccount(
            username=username or unique_username("dm"),
            password_hash=hash_password("abc12345", rounds=4),   # 测试数据，cost 取最低
            password_algo="bcrypt",
            role="user",
            terms_agreed_at=now,
            agreement_version="v1.0",
            email=email,
            email_verified_at=verified_at,
            created_at=now,
            updated_at=now,
        )
        s.add(acc)
        s.commit()
        return int(acc.id)


def add_vcode(user_id: int, code: str, *, ttl_minutes: int = 15, age_minutes: int = 0,
              consumed_at=None, attempt_count: int = 0,
              purpose: str = PURPOSE_PASSWORD_RESET) -> int:
    """建验证码行；``age_minutes`` = 签发于多少分钟前（用于造「已过期但仍满足 CHECK」）。"""
    factory = get_session_factory()
    created = now_local() - timedelta(minutes=age_minutes)
    with factory() as s:
        row = VerificationCode(
            user_id=user_id,
            purpose=purpose,
            code_hash=hash_verification_code(PEPPER, user_id, purpose, code),
            expires_at=created + timedelta(minutes=ttl_minutes),
            consumed_at=consumed_at,
            attempt_count=attempt_count,
            created_at=created,
        )
        s.add(row)
        s.commit()
        return int(row.id)


def add_prt(user_id: int, token: str, *, ttl_minutes: int = 15, age_minutes: int = 0,
            consumed_at=None, revoked_at=None) -> int:
    factory = get_session_factory()
    created = now_local() - timedelta(minutes=age_minutes)
    with factory() as s:
        row = PasswordResetToken(
            user_id=user_id,
            token_hash=hash_reset_token(token),
            expires_at=created + timedelta(minutes=ttl_minutes),
            consumed_at=consumed_at,
            revoked_at=revoked_at,
            created_at=created,
        )
        s.add(row)
        s.commit()
        return int(row.id)


def outstanding_vcodes(user_id: int) -> int:
    """「有效验证码」判定（与 ``VerificationCode`` 冻结口径一致）。"""
    return int(scalar(
        "SELECT COUNT(*) FROM verification_code WHERE user_id=:u AND consumed_at IS NULL "
        "AND expires_at > NOW() AND attempt_count < :m",
        u=user_id, m=CODE_MAX_ATTEMPTS))


def outstanding_prts(user_id: int) -> int:
    return int(scalar(
        "SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u "
        "AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at > NOW()",
        u=user_id))


# ══════════════════════════════════════════════════════════════════
# §八.1 多个 email=NULL 用户可以共存
# ══════════════════════════════════════════════════════════════════
def test_multiple_null_emails_coexist() -> None:
    tag = "nullemail"
    for _ in range(4):
        add_account(username=unique_username(tag))
    n = scalar("SELECT COUNT(*) FROM user_account WHERE username LIKE :p "
               "AND email IS NULL AND email_verified_at IS NULL", p=prefix(tag))
    assert int(n) == 4


# ══════════════════════════════════════════════════════════════════
# §八.2 规范化后同一「已绑定」邮箱不能重复（**DB 级**，不只应用层）
# ══════════════════════════════════════════════════════════════════
def test_duplicate_canonical_email_rejected() -> None:
    add_account(email="dup1@example.com")
    with pytest.raises(IntegrityError):
        add_account(email="dup1@example.com")


def test_case_variant_email_rejected_at_db_level() -> None:
    """即使应用层规范化回归，DB 仍阻断 —— 列级 ``utf8mb4_0900_as_ci`` 的意义。"""
    add_account(email="case1@example.com")
    with pytest.raises(IntegrityError):
        add_account(email="CASE1@EXAMPLE.COM")


def test_accent_variant_email_allowed() -> None:
    """重音敏感 ⇒ 不误伤 ``café@x.com`` / ``cafe@x.com`` 这类**合法不同**地址。"""
    add_account(email="café@x.com")
    add_account(email="cafe@x.com")
    n = scalar("SELECT COUNT(*) FROM user_account WHERE email IN ('café@x.com','cafe@x.com')")
    assert int(n) == 2


def test_email_unique_index_is_registered_and_unique() -> None:
    r = rows("SELECT NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME FROM information_schema.STATISTICS "
             "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_account' "
             "AND INDEX_NAME='uk_user_account_email' ORDER BY SEQ_IN_INDEX")
    assert [(int(x[0]), int(x[1]), x[2]) for x in r] == [(0, 1, "email")]


def test_email_column_collation_is_frozen() -> None:
    assert scalar("SELECT COLLATION_NAME FROM information_schema.COLUMNS "
                  "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_account' "
                  "AND COLUMN_NAME='email'") == EMAIL_COLLATION == "utf8mb4_0900_as_ci"


# ══════════════════════════════════════════════════════════════════
# §八.3 ``email_verified_at`` 可 NULL ＋「同时为空/同时非空」不变量
# ══════════════════════════════════════════════════════════════════
def test_email_pair_check_rejects_half_filled() -> None:
    with pytest.raises((IntegrityError, OperationalError)):
        add_account(email="half1@example.com", verified_at=None)   # 有邮箱、未标验证
    with pytest.raises((IntegrityError, OperationalError)):
        add_account(email=None, verified_at=now_local())           # 无邮箱、却标了验证


def test_email_pair_check_is_registered() -> None:
    r = rows("SELECT cc.CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS cc "
             "JOIN information_schema.TABLE_CONSTRAINTS tc "
             " ON tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME "
             " AND tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA "
             "WHERE cc.CONSTRAINT_SCHEMA=DATABASE() AND tc.TABLE_NAME='user_account'")
    assert {x[0] for x in r} >= {"ck_user_account_email_pair"}


# ══════════════════════════════════════════════════════════════════
# §八.4/§八.5 验证码与 reset token **绝不明文入库**
# ══════════════════════════════════════════════════════════════════
def test_verification_code_plaintext_never_stored() -> None:
    uid = add_account()
    code = "987654"
    row_id = add_vcode(uid, code)
    row = rows("SELECT id,user_id,purpose,code_hash,expires_at,consumed_at,attempt_count,"
               "created_at FROM verification_code WHERE id=:i", i=row_id)[0]
    assert all(str(v) != code for v in row), "存在与明文验证码相等的列值"
    assert code not in str(row[3]), "code_hash 含明文子串"
    assert len(str(row[3])) == 64


def test_reset_token_plaintext_never_stored() -> None:
    uid = add_account()
    token = "RAW-RESET-TOKEN-MUST-NEVER-APPEAR"
    row_id = add_prt(uid, token)
    row = rows("SELECT id,user_id,token_hash,expires_at,consumed_at,revoked_at,created_at "
               "FROM password_reset_token WHERE id=:i", i=row_id)[0]
    assert all(str(v) != token for v in row), "存在与原始 token 相等的列值"
    assert token not in str(row[2])
    assert len(str(row[2])) == 64


@pytest.mark.parametrize(
    "table,expected",
    (("verification_code", EXPECT_VCODE_COLS), ("password_reset_token", EXPECT_PRT_COLS)),
)
def test_new_table_columns_frozen_and_no_plaintext_column(table: str, expected: tuple) -> None:
    got = tuple(x[0] for x in rows(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME=:t ORDER BY ORDINAL_POSITION", t=table))
    assert got == expected
    for col in got:
        if col.endswith("_hash"):
            continue
        assert col not in PLAINTEXT_COL_BLACKLIST, f"可疑明文列：{table}.{col}"


# ══════════════════════════════════════════════════════════════════
# §八.6~§八.8 验证码：过期 / consumed / 限次 / 新码顶旧码
# ══════════════════════════════════════════════════════════════════
def test_verification_code_expiry_is_decidable() -> None:
    uid = add_account()
    add_vcode(uid, "111111", ttl_minutes=15, age_minutes=60)   # 已过期：expires=now-45min
    add_vcode(uid, "222222", ttl_minutes=15)                   # 仍有效：expires=now+15min
    assert outstanding_vcodes(uid) == 1
    assert int(scalar("SELECT COUNT(*) FROM verification_code WHERE user_id=:u "
                      "AND expires_at <= NOW()", u=uid)) == 1


def test_verification_code_consumed_is_decidable() -> None:
    uid = add_account()
    add_vcode(uid, "333333")
    add_vcode(uid, "444444", consumed_at=now_local())
    assert outstanding_vcodes(uid) == 1
    assert int(scalar("SELECT COUNT(*) FROM verification_code WHERE user_id=:u "
                      "AND consumed_at IS NOT NULL", u=uid)) == 1


def test_attempt_count_supports_rate_limit() -> None:
    uid = add_account()
    add_vcode(uid, "555555", attempt_count=CODE_MAX_ATTEMPTS)       # 已达上限 ⇒ 无效
    add_vcode(uid, "666666", attempt_count=CODE_MAX_ATTEMPTS - 1)   # 尚可一搏
    assert outstanding_vcodes(uid) == 1
    with get_session_factory()() as s:      # 服务端递增能力（B2 使用）
        s.execute(update(VerificationCode).where(VerificationCode.user_id == uid)
                  .values(attempt_count=CODE_MAX_ATTEMPTS))
        s.commit()
    assert outstanding_vcodes(uid) == 0


def test_new_code_supersedes_old_code_capability() -> None:
    """``CODE_MAX_ACTIVE_PER_PURPOSE = 1`` ⇒ 签发新码时把旧码置 ``consumed`` 即可表达。"""
    uid = add_account()
    old = add_vcode(uid, "777777")
    add_vcode(uid, "888888")
    assert outstanding_vcodes(uid) == 2      # 数据层允许并存（策略由服务端施加）
    with get_session_factory()() as s:
        s.execute(update(VerificationCode).where(VerificationCode.id == old)
                  .values(consumed_at=now_local()))
        s.commit()
    assert outstanding_vcodes(uid) == 1


def test_vcode_expiry_check_enforced() -> None:
    uid = add_account()
    with pytest.raises((IntegrityError, OperationalError)):
        add_vcode(uid, "999999", ttl_minutes=0)     # expires_at == created_at ⇒ 违反 CHECK


# ══════════════════════════════════════════════════════════════════
# §八.9~§八.11 reset token：三态 / 不可重放 / 批量作废能力
# ══════════════════════════════════════════════════════════════════
def test_reset_token_three_states() -> None:
    uid = add_account()
    add_prt(uid, "tok-valid-1")
    add_prt(uid, "tok-expired", ttl_minutes=15, age_minutes=60)
    add_prt(uid, "tok-consumed", consumed_at=now_local())
    add_prt(uid, "tok-revoked", revoked_at=now_local())
    assert outstanding_prts(uid) == 1
    assert int(scalar("SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u "
                      "AND consumed_at IS NOT NULL", u=uid)) == 1
    assert int(scalar("SELECT COUNT(*) FROM password_reset_token WHERE user_id=:u "
                      "AND revoked_at IS NOT NULL", u=uid)) == 1


def test_reset_token_replay_is_unusable() -> None:
    uid = add_account()
    row_id = add_prt(uid, "tok-once")
    assert outstanding_prts(uid) == 1
    with get_session_factory()() as s:
        s.execute(update(PasswordResetToken).where(PasswordResetToken.id == row_id)
                  .values(consumed_at=now_local()))
        s.commit()
    assert outstanding_prts(uid) == 0


def test_batch_invalidate_outstanding_by_user_capability() -> None:
    """``E-24`` 所需能力：按 ``user_id`` **一条 UPDATE 批量作废未消费凭证**。

    事务内执行后 **ROLLBACK** —— 只证明语句可用，不留任何副作用。
    """
    uid = add_account()
    add_prt(uid, "tok-b1")
    add_prt(uid, "tok-b2")
    add_prt(uid, "tok-b3")
    add_prt(uid, "tok-b4-consumed", consumed_at=now_local())
    assert outstanding_prts(uid) == 3

    with get_session_factory()() as s:
        result = s.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == uid,
                PasswordResetToken.consumed_at.is_(None),
                PasswordResetToken.revoked_at.is_(None),
            )
            .values(revoked_at=now_local())
        )
        assert result.rowcount == 3, f"批量作废命中 {result.rowcount} 行（期望 3）"
        s.rollback()
    assert outstanding_prts(uid) == 3, "ROLLBACK 未生效（留下了副作用）"


def test_vcode_rows_locatable_by_user_for_cleanup() -> None:
    """§八.12 注销时可**按 user_id 定位**该用户的 verification / reset 数据。"""
    uid = add_account()
    add_vcode(uid, "123123")
    add_vcode(uid, "321321")
    add_prt(uid, "tok-c1")
    assert int(scalar("SELECT COUNT(*) FROM verification_code WHERE user_id=:u", u=uid)) == 2
    assert int(scalar("SELECT COUNT(*) FROM password_reset_token "
                      "WHERE user_id=:u", u=uid)) == 1
    # 且可用「一条语句按用户集合清理」表达（B5 扩展 A-07 时使用）
    with get_engine().connect() as conn:
        n1 = conn.execute(
            text("SELECT COUNT(*) FROM verification_code WHERE user_id IN :ids")
            .bindparams(bindparam("ids", expanding=True)), {"ids": [uid]}).scalar()
    assert int(n1) == 2


# ══════════════════════════════════════════════════════════════════
# §八.13 0 外键（与既有 8 表架构一致）
# ══════════════════════════════════════════════════════════════════
def test_database_has_zero_foreign_keys() -> None:
    r = rows("SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
             "WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='FOREIGN KEY'")
    assert r == [], f"出现了外键：{r}"


def test_metadata_declares_no_foreign_key() -> None:
    from app.models import Base

    for table in Base.metadata.tables.values():
        assert not list(table.foreign_keys), f"{table.name} 声明了外键"


# ══════════════════════════════════════════════════════════════════
# schema 级冻结：索引 / CHECK / 总量 / 版本
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "table,expected",
    (("verification_code", EXPECT_VCODE_IDX), ("password_reset_token", EXPECT_PRT_IDX)),
)
def test_new_table_indexes_frozen(table: str, expected: dict) -> None:
    got: dict = {}
    for name, non_unique, _seq, col in rows(
        "SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME=:t ORDER BY INDEX_NAME, SEQ_IN_INDEX", t=table):
        if name == "PRIMARY":
            continue
        slot = got.setdefault(name, [1 - int(non_unique), []])
        slot[1].append(col)
    assert {k: (v[0], tuple(v[1])) for k, v in got.items()} == expected


def test_new_table_checks_registered() -> None:
    got = {x[0]: x[1] for x in rows(
        "SELECT tc.TABLE_NAME, cc.CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS cc "
        "JOIN information_schema.TABLE_CONSTRAINTS tc "
        " ON tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME "
        " AND tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA "
        "WHERE cc.CONSTRAINT_SCHEMA=DATABASE()")}
    assert got.get("verification_code") == "ck_vcode_expiry_after_created"
    assert got.get("password_reset_token") == "ck_prt_expiry_after_created"


def test_total_table_and_index_counts() -> None:
    assert int(scalar("SELECT COUNT(*) FROM information_schema.TABLES "
                      "WHERE TABLE_SCHEMA=DATABASE()")) == 11, "应为 11 张表（10 业务 + 1 alembic）"
    assert int(scalar("SELECT COUNT(DISTINCT TABLE_NAME, INDEX_NAME) "
                      "FROM information_schema.STATISTICS "
                      "WHERE TABLE_SCHEMA=DATABASE() AND INDEX_NAME<>'PRIMARY'")) == 23, \
        "业务索引应为 23（0001 的 17 + 0003 的 6）"


def test_revision_is_0003() -> None:
    assert scalar("SELECT version_num FROM alembic_version") == "0003_password_reset_email"


# ══════════════════════════════════════════════════════════════════
# ORM ↔ DB 一致性（``models`` 声明与真实库不得漂移）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("table", ("verification_code", "password_reset_token",
                                   "user_account", "user_profile", "user_session"))
def test_orm_columns_match_database(table: str) -> None:
    from app.models import Base

    orm_cols = {c.name for c in Base.metadata.tables[table].columns}
    db_cols = {x[0] for x in rows(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME=:t", t=table)}
    # user_account 的 2 个新列由 ALTER 追加到物理末尾 ⇒ 用集合比较而非序列比较
    assert orm_cols == db_cols, f"{table} ORM 与 DB 列不一致"
