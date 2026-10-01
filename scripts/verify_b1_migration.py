# -*- coding: utf-8 -*-
"""B1 迁移四段往返验证（``0002 → 0003 → 0002 → 0003``）＋ 存量业务数据零漂移对拍。

用法（在工程根执行）::

    Demo\\backend\\.venv\\Scripts\\python.exe scripts\\verify_b1_migration.py

纪律
----
- **只读 DB**：本脚本自己不做任何 DML；唯一的写是调用 ``alembic upgrade/downgrade``
  （即被测对象本身），且**只涉及 0003 新增的 2 张表 ＋ user_account 的 2 个新列**。
- **期望值全部硬编码**在本文件顶部（铁律⑨：期望值不得取自被测对象自身）。
- **不回显任何敏感值**：``password_hash`` / 健康字段 / 邮箱一律只进**聚合摘要**。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PY = BACKEND / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / ".workbuddy" / "_b1_migration_out.txt"

# ══════════════════════════════════════════════════════════════════
# 期望值（**硬编码**，不得从被测对象反推）
# ══════════════════════════════════════════════════════════════════
REV_0002 = "0002_user_profile_avatar"
REV_0003 = "0003_password_reset_email"

BASE_TABLES = (
    "alembic_version", "export_job", "health_goal", "health_record",
    "login_failure_state", "record_tag", "user_account", "user_profile", "user_session",
)
NEW_TABLES = ("password_reset_token", "verification_code")

EXPECT_USER_ACCOUNT_COLS = (
    "id", "username", "password_hash", "password_algo", "role",
    "terms_agreed_at", "agreement_version", "created_at", "updated_at",
    "email", "email_verified_at",
)
EXPECT_VCODE_COLS = (
    "id", "user_id", "purpose", "code_hash", "expires_at",
    "consumed_at", "attempt_count", "created_at",
)
EXPECT_PRT_COLS = (
    "id", "user_id", "token_hash", "expires_at",
    "consumed_at", "revoked_at", "created_at",
)
EXPECT_0003_INDEXES = {
    "user_account": {"uk_user_account_email": (1, ("email",))},
    "verification_code": {
        "idx_vcode_user_purpose": (0, ("user_id", "purpose", "consumed_at")),
        "idx_vcode_expires": (0, ("expires_at",)),
    },
    "password_reset_token": {
        "uk_prt_token_hash": (1, ("token_hash",)),
        "idx_prt_user_outstanding": (0, ("user_id", "consumed_at", "revoked_at")),
        "idx_prt_expires": (0, ("expires_at",)),
    },
}
EXPECT_0003_CHECKS = {
    "user_account": "ck_user_account_email_pair",
    "verification_code": "ck_vcode_expiry_after_created",
    "password_reset_token": "ck_prt_expiry_after_created",
}
#: 业务表（不含 alembic_version）—— 存量业务数据摘要必须逐段不变
BUSINESS_TABLES = tuple(t for t in BASE_TABLES if t != "alembic_version")

RESULTS = []


def record(section: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((section, name, bool(ok), detail))


def run_alembic(*args: str) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [str(PY), "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=str(BACKEND), capture_output=True, text=True, env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ── DB 只读快照 ────────────────────────────────────────────────────
def load_env() -> dict:
    cfg: dict = {}
    for name in (".env.development", ".env"):
        p = BACKEND / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def _norm(v) -> str:
    if v is None:
        return "\x00NULL"
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return str(v)


class Snap:
    """一次 schema + 数据快照（**只记元数据与聚合摘要，不记值**）。"""

    def __init__(self) -> None:
        import pymysql

        env = load_env()
        self.db = env.get("MYSQL_DB", "kangji_healthtrack")
        self.conn = pymysql.connect(
            host=env.get("MYSQL_HOST", "127.0.0.1"), port=int(env.get("MYSQL_PORT", 3306)),
            user=env.get("MYSQL_USER"), password=env.get("MYSQL_PASSWORD"),
            database=self.db, charset="utf8mb4", autocommit=True,
        )
        self.cur = self.conn.cursor()

    def close(self) -> None:
        self.conn.close()

    def q(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.fetchall()

    # ── schema ──
    def revision(self) -> str:
        rows = self.q("SELECT version_num FROM alembic_version")
        return rows[0][0] if rows else ""

    def tables(self) -> tuple:
        return tuple(sorted(r[0] for r in self.q(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (self.db,))))

    def columns(self, table: str) -> tuple:
        return tuple(r[0] for r in self.q(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
            "AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (self.db, table)))

    def column_detail(self, table: str) -> tuple:
        return tuple(
            (r[0], r[1], r[2], r[3], r[5]) for r in self.q(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLLATION_NAME "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "ORDER BY ORDINAL_POSITION", (self.db, table)))

    def indexes(self) -> dict:
        """返回 ``{表: {索引名: (is_unique, 列序)}}``；``is_unique``：1 = 唯一（**已把
        ``information_schema.STATISTICS.NON_UNIQUE`` 取反**，避免落进「1 到底是唯一还是
        非唯一」的经典陷阱）。``PRIMARY`` 不计入（每表必有一个 ⇒ 无鉴别力）。
        """
        rows = self.q(
            "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
            "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s "
            "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX", (self.db,))
        out: dict = {}
        for t, name, nu, seq, col in rows:
            if name == "PRIMARY":
                continue
            slot = out.setdefault(t, {}).setdefault(name, [1 - int(nu), []])
            slot[0] = 1 - int(nu)
            slot[1].append(col)
        return {t: {n: (v[0], tuple(v[1])) for n, v in d.items()} for t, d in out.items()}

    def index_fingerprint(self) -> tuple:
        idx = self.indexes()
        return tuple(sorted(
            (t, n, v[0], v[1]) for t, d in idx.items() for n, v in d.items()))

    def checks(self) -> tuple:
        return tuple(sorted(
            (r[2], r[0]) for r in self.q(
                "SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE, tc.TABLE_NAME "
                "FROM information_schema.CHECK_CONSTRAINTS cc "
                "JOIN information_schema.TABLE_CONSTRAINTS tc "
                "  ON tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME "
                " AND tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA "
                "WHERE cc.CONSTRAINT_SCHEMA=%s", (self.db,))))

    # ── 数据 ──
    def row_counts(self) -> dict:
        return {t: int(self.q(f"SELECT COUNT(*) FROM `{t}`")[0][0])
                for t in self.tables()}

    def digest(self, table: str, cols: tuple, order_col: str = "id") -> str:
        """按**固定投影** ``cols`` 取整表做**聚合摘要**（不打印任何原始值）。

        ⚠️ 投影必须固定：若直接按「当前列」取，``0003`` 给 ``user_account`` 加了 2 列
        后摘要**必然**变化，会把「加了列」误判成「数据被改」（本脚本首跑即踩此坑）。
        """
        rows = self.q(f"SELECT `{'`,`'.join(cols)}` FROM `{table}` ORDER BY `{order_col}`")
        h = hashlib.sha256()
        for row in rows:
            h.update("\x1f".join(_norm(v) for v in row).encode("utf-8"))
            h.update(b"\x1e")
        return h.hexdigest()

    def legacy_digests(self, projection: dict) -> dict:
        order = {"login_failure_state": "username"}
        return {t: self.digest(t, projection[t], order.get(t, "id")) for t in BUSINESS_TABLES}

    def legacy_emails_all_null(self) -> tuple:
        total = int(self.q("SELECT COUNT(*) FROM user_account")[0][0])
        nonnull = int(self.q(
            "SELECT COUNT(*) FROM user_account WHERE email IS NOT NULL "
            "OR email_verified_at IS NOT NULL")[0][0])
        return nonnull == 0, total, nonnull

    def legacy_emails_all_null_excluding_tests(self) -> tuple:
        """仅统计**非测试账号**（排除 ``tst%``）—— 归位 downgrade 前的**数据安全前置**。

        ``0002`` 没有 ``email`` 列 ⇒ 若此刻非测试账号中已有非 NULL 邮箱，
        则 ``downgrade`` 会**不可逆地丢掉**它 ⇒ 必须 ABORT，而不是硬跑。
        （测试账号的 ``tst`` 行由 pytest 守卫自清理，不参与该前置。）

        ⚠️ **只能在 ``revision == 0003`` 时调用**：本查询会 ``SELECT ... email``，
        而 ``0002`` 无该列 ⇒ 会报 ``1054``（调用方已用 ``if cur_rev == REV_0003`` 把关）。
        """
        p = "tst%"
        total = int(self.q(
            "SELECT COUNT(*) FROM user_account WHERE username NOT LIKE %s", (p,))[0][0])
        nonnull = int(self.q(
            "SELECT COUNT(*) FROM user_account WHERE username NOT LIKE %s AND ("
            "email IS NOT NULL OR email_verified_at IS NOT NULL)", (p,))[0][0])
        return nonnull == 0, total, nonnull


def main() -> None:
    buf = io.StringIO()

    def say(s: str = "") -> None:
        buf.write(s + "\n")
        print(s)

    say("=" * 84)
    say("B1 迁移四段往返验证：0002 → 0003 → 0002 → 0003 ＋ 存量业务数据零漂移对拍")
    say("=" * 84)

    snap = Snap()
    snapshots: dict = {}
    #: 固定投影 = **0002 时刻的列集合**（首段取值后冻结，四段全程共用）
    projection: dict = {}

    def take(tag: str) -> dict:
        cols = {t: snap.columns(t) for t in snap.tables()}
        for t in BUSINESS_TABLES:
            projection.setdefault(t, cols[t])
        s = {
            "revision": snap.revision(),
            "tables": snap.tables(),
            "counts": snap.row_counts(),
            "business_counts": {t: int(snap.q(f"SELECT COUNT(*) FROM `{t}`")[0][0])
                                for t in BUSINESS_TABLES},
            "digests": snap.legacy_digests(projection),
            "indexes": snap.index_fingerprint(),
            "checks": snap.checks(),
            "columns": cols,
            "index_n": sum(len(v) for v in snap.indexes().values()),
        }
        snapshots[tag] = s
        say("[%s] revision=%-28s tables=%d 业务索引=%d" %
            (tag, s["revision"], len(s["tables"]), s["index_n"]))
        return s

    say("\n【基线】工程根=%s" % ROOT)
    env = load_env()
    say("       DB=%s@%s:%s" % (env.get("MYSQL_DB"), env.get("MYSQL_HOST"), env.get("MYSQL_PORT")))

    # ══ 前段 0：归位到 0002（使本脚本**可重复运行**）══════════════════
    say("\n── 前段 0：把库归位到 0002（幂等；允许上一次跑完停在 0003 时直接重跑）──")
    cur_rev = snap.revision()
    say("   当前 revision = %s" % cur_rev)

    if cur_rev == REV_0003:
        # 数据安全前置（**仅在 0003 时需要**：0002 没有 email 列 ⇒ 无列可丢）：
        # downgrade 会 DROP email 列 ⇒ 非测试账号若已有邮箱，宁可不跑。
        safe, n_legacy, n_nonnull = snap.legacy_emails_all_null_excluding_tests()
        say("   非测试账号 = %d ；其中已填 email / email_verified_at 的 = %d"
            % (n_legacy, n_nonnull))
        record("前段0", "数据安全前置：非测试账号邮箱全 NULL（downgrade 不丢数据）", safe,
               "total=%d nonnull=%d" % (n_legacy, n_nonnull))
        if not safe:
            say("   ‼ 非测试账号存在非 NULL 邮箱 ⇒ downgrade 会不可逆丢数据 ⇒ ABORT（不做任何写）")
            snap.close()
            sys.exit(3)

        rc, log = run_alembic("downgrade", REV_0002)
        say("   已 downgrade → 0002（rc=%d）" % rc)
        record("前段0", "归位 downgrade 退出码 = 0", rc == 0, log.strip()[-220:])
        cur_rev = snap.revision()
        say("   归位后 revision = %s" % cur_rev)
    else:
        record("前段0", "无需归位（当前已是 0002，无列可丢）", cur_rev == REV_0002, cur_rev)
    record("前段0", "归位后 revision = 0002", cur_rev == REV_0002, cur_rev)
    if cur_rev != REV_0002:
        say("   ‼ 无法归位到 0002（既非 0002 也非 0003）⇒ ABORT")
        snap.close()
        sys.exit(3)

    s0 = take("P0 起始")

    record("P0", "起始版本 = 0002", s0["revision"] == REV_0002, s0["revision"])
    record("P0", "起始表集 = 9 张", s0["tables"] == tuple(sorted(BASE_TABLES)),
           ",".join(s0["tables"]))
    record("P0", "起始业务索引 = 17", s0["index_n"] == 17, str(s0["index_n"]))
    record("P0", "起始 user_account 列 = 9",
           s0["columns"]["user_account"] == EXPECT_USER_ACCOUNT_COLS[:9],
           ",".join(s0["columns"]["user_account"]))

    # ── 段 1：0002 → 0003 ──────────────────────────────────────────
    say("\n── 段 1：alembic upgrade → 0003 ──")
    rc, log = run_alembic("upgrade", REV_0003)
    say("   rc=%d" % rc)
    for line in log.strip().splitlines()[-6:]:
        say("   | " + line)
    record("段1", "alembic upgrade 退出码 = 0", rc == 0, log.strip()[-220:])
    s1 = take("P1 升级后")

    record("段1", "版本 = 0003", s1["revision"] == REV_0003, s1["revision"])
    record("段1", "表集 = 11 张（9 + 2）",
           s1["tables"] == tuple(sorted(BASE_TABLES + NEW_TABLES)), ",".join(s1["tables"]))
    record("段1", "user_account 列 = 11 且顺序冻结",
           s1["columns"]["user_account"] == EXPECT_USER_ACCOUNT_COLS,
           ",".join(s1["columns"]["user_account"]))
    record("段1", "verification_code 列 = 8 且顺序冻结",
           s1["columns"]["verification_code"] == EXPECT_VCODE_COLS,
           ",".join(s1["columns"]["verification_code"]))
    record("段1", "password_reset_token 列 = 7 且顺序冻结",
           s1["columns"]["password_reset_token"] == EXPECT_PRT_COLS,
           ",".join(s1["columns"]["password_reset_token"]))

    idx1 = snap.indexes()
    for tbl, want in EXPECT_0003_INDEXES.items():
        for name, (uniq, cols) in want.items():
            got = idx1.get(tbl, {}).get(name)
            record("段1", "%s.%s 唯一性/列序正确" % (tbl, name), got == (uniq, cols), str(got))

    chk1 = dict(snap.checks())
    for tbl, name in EXPECT_0003_CHECKS.items():
        record("段1", "%s 存在 CHECK %s" % (tbl, name), chk1.get(tbl) == name, str(chk1.get(tbl)))

    # 邮箱列类型 / 可空 / 排序规则
    det = dict((r[0], r) for r in snap.column_detail("user_account"))
    em = det["email"]
    record("段1", "email 类型 = varchar(254)", em[1] == "varchar(254)", em[1])
    record("段1", "email 可空（NULL 允许）", em[2] == "YES", em[2])
    record("段1", "email 无默认值（不回填）", em[3] is None, str(em[3]))
    record("段1", "email 列级排序规则 = utf8mb4_0900_as_ci",
           em[4] == "utf8mb4_0900_as_ci", str(em[4]))
    ev = det["email_verified_at"]
    record("段1", "email_verified_at 类型 = datetime 且可空",
           ev[1] == "datetime" and ev[2] == "YES", "%s/%s" % (ev[1], ev[2]))

    # 存量兼容：邮箱全 NULL / 数据零漂移 / 行数零变化
    allnull, total, nonnull = snap.legacy_emails_all_null()
    record("段1", "存量 %d 个账号 email / email_verified_at 全为 NULL（非 NULL 行数=%d）"
           % (total, nonnull), allnull, "total=%d nonnull=%d" % (total, nonnull))
    record("段1", "存量业务数据摘要逐表不变", s1["digests"] == s0["digests"], "")
    for t in BUSINESS_TABLES:
        record("段1", "表 %s 行数不变" % t, s1["counts"][t] == s0["counts"][t],
               "%s → %s" % (s0["counts"][t], s1["counts"][t]))
    # 既有列定义零漂移
    drift = []
    for t in BASE_TABLES:
        if t == "alembic_version":
            continue
        before = tuple(c for c in s0["columns"][t])
        after = tuple(c for c in s1["columns"][t] if c in before)
        if before != after:
            drift.append(t)
    record("段1", "既有 8 表列定义零漂移（无改名/删除/换序）", not drift, ",".join(drift))
    old_idx = set(s0["indexes"])
    new_idx = set(s1["indexes"])
    record("段1", "既有索引全部保留（新增 6 个、删除 0 个）",
           old_idx <= new_idx and len(new_idx) - len(old_idx) == 6,
           "old=%d new=%d" % (len(old_idx), len(new_idx)))

    # ── 段 2：0003 → 0002 ──────────────────────────────────────────
    say("\n── 段 2：alembic downgrade → 0002 ──")
    rc, log = run_alembic("downgrade", REV_0002)
    say("   rc=%d" % rc)
    for line in log.strip().splitlines()[-6:]:
        say("   | " + line)
    record("段2", "alembic downgrade 退出码 = 0", rc == 0, log.strip()[-220:])
    s2 = take("P2 回退后")

    record("段2", "版本 = 0002", s2["revision"] == REV_0002, s2["revision"])
    record("段2", "表集回到 9 张", s2["tables"] == tuple(sorted(BASE_TABLES)),
           ",".join(s2["tables"]))
    record("段2", "user_account 列回到 9 且顺序不变",
           s2["columns"]["user_account"] == EXPECT_USER_ACCOUNT_COLS[:9],
           ",".join(s2["columns"]["user_account"]))
    record("段2", "业务索引回到 17", s2["index_n"] == 17, str(s2["index_n"]))
    record("段2", "索引指纹逐字回到 P0", s2["indexes"] == s0["indexes"], "")
    record("段2", "CHECK 集合逐字回到 P0", s2["checks"] == s0["checks"], "")
    record("段2", "存量业务数据摘要逐表不变", s2["digests"] == s0["digests"], "")
    record("段2", "存量 8 表行数逐表回到 P0", s2["business_counts"] == s0["business_counts"], "")

    # ── 段 3：0002 → 0003（再次）──────────────────────────────────
    say("\n── 段 3：alembic upgrade → 0003（再次）──")
    rc, log = run_alembic("upgrade", REV_0003)
    say("   rc=%d" % rc)
    for line in log.strip().splitlines()[-6:]:
        say("   | " + line)
    record("段3", "alembic upgrade 退出码 = 0（可重复升级）", rc == 0, log.strip()[-220:])
    s3 = take("P3 最终")

    record("段3", "最终版本 = 0003", s3["revision"] == REV_0003, s3["revision"])
    record("段3", "最终表集 = 11 张", s3["tables"] == tuple(sorted(BASE_TABLES + NEW_TABLES)),
           ",".join(s3["tables"]))
    record("段3", "schema 与 P1 逐字一致（幂等）",
           s3["indexes"] == s1["indexes"] and s3["checks"] == s1["checks"]
           and s3["columns"] == s1["columns"], "")
    record("段3", "存量业务数据摘要逐表不变（贯穿四段）", s3["digests"] == s0["digests"], "")
    record("段3", "存量 8 表行数逐表 = P0（新表不计入对比）",
           s3["business_counts"] == s0["business_counts"],
           ",".join("%s:%s→%s" % (t, s0["business_counts"][t], s3["business_counts"][t])
                    for t in BUSINESS_TABLES if s0["business_counts"][t] != s3["business_counts"][t]))
    allnull3, total3, nonnull3 = snap.legacy_emails_all_null()
    record("段3", "存量 %d 账号邮箱仍全 NULL（非 NULL 行数=%d）" % (total3, nonnull3),
           allnull3, "nonnull=%d" % nonnull3)
    record("段3", "新表初始行数 = 0",
           s3["counts"]["verification_code"] == 0 and s3["counts"]["password_reset_token"] == 0,
           "vcode=%s prt=%s" % (s3["counts"]["verification_code"],
                                s3["counts"]["password_reset_token"]))

    # 列总数对拍
    col_total = {k: sum(len(v) for v in s["columns"].values()) for k, s in snapshots.items()}
    say("\n【摘要投影披露】存量 8 表摘要按**固定投影**计算（列清单见下；值一律只进摘要）")
    for t in BUSINESS_TABLES:
        say("   %-22s cols=%d %s" % (t, len(projection[t]), ",".join(projection[t])))
    say("\n【列总数对拍】" + " | ".join("%s=%d" % (k, v) for k, v in col_total.items()))
    record("对拍", "列总数 P0 → P3 净增 17", col_total["P3 最终"] - col_total["P0 起始"] == 17,
           "%d → %d" % (col_total["P0 起始"], col_total["P3 最终"]))
    record("对拍", "P1 与 P3 列总数一致", col_total["P1 升级后"] == col_total["P3 最终"], "")

    snap.close()

    # ── 汇总 ──────────────────────────────────────────────────────
    total_n = len(RESULTS)
    fail = [r for r in RESULTS if not r[2]]
    say("\n" + "=" * 84)
    say("【判定矩阵】共 %d 项：PASS %d / FAIL %d" % (total_n, total_n - len(fail), len(fail)))
    say("=" * 84)
    for section in ("前段0", "P0", "段1", "段2", "段3", "对拍"):
        rows = [r for r in RESULTS if r[0] == section]
        ok = sum(1 for r in rows if r[2])
        say("  [%s] %d/%d" % (section, ok, len(rows)))
        for _, name, good, detail in rows:
            if not good:
                say("      ✗ %s  ⟵ %s" % (name, detail[:160]))
    say("\n最终版本 = %s" % snapshots["P3 最终"]["revision"])
    say("结论：%s" % ("全部 PASS" if not fail else "存在 FAIL，见上"))

    payload = {
        "results": [{"section": s, "name": n, "ok": o, "detail": d} for s, n, o, d in RESULTS],
        "total": total_n, "fail": len(fail),
        "col_total": col_total,
        "index_total": {k: v["index_n"] for k, v in snapshots.items()},
        "table_total": {k: len(v["tables"]) for k, v in snapshots.items()},
        "row_counts_final": snapshots["P3 最终"]["counts"],
    }
    OUT.write_text(buf.getvalue() + "\n\n[JSON]\n" + json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("\n落盘：%s" % OUT)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
