# -*- coding: utf-8 -*-
"""S2 第八批 A-07 —— 测试数据清理脚本（白名单 · 显式清单 · 清理前快照 · 事务内自校验）。

用法::

    backend\\.venv\\Scripts\\python.exe scripts\\b8_cleanup_testdata.py --dry-run      # 只报告，不动数据
    backend\\.venv\\Scripts\\python.exe scripts\\b8_cleanup_testdata.py --snapshot     # 只落盘快照
    backend\\.venv\\Scripts\\python.exe scripts\\b8_cleanup_testdata.py --apply        # 执行清理（单事务）
    backend\\.venv\\Scripts\\python.exe scripts\\b8_cleanup_testdata.py --apply --purge-files
                                                                                    # 追加删除登记过的导出文件

默认 **不触碰文件系统**（数据库清理与文件清理解耦）；只有显式加 ``--purge-files``
才会删除快照登记过的导出文件，以及**空的**清理重试登记文件。

安全设计（强约束）：
1. **白名单闸门**：候选账号只能来自 ``user_account.username``，且必须**逐字符**匹配
   ``^tst[a-z0-9_]{1,16}$``（本批全部测试账号前缀 ``tst``）。任一候选不匹配 → **整体 ABORT**，
   一行都不删。
2. **显式清单**：不靠通配符直接删业务表；先把候选账号枚举为**具体 id 列表 / 用户名列表**，
   再进行 ``IN (...)`` 删除。空集合时用恒假条件（``1 = 0``），**绝不生成 ``IN ()``**（会 1064）。
3. **清理前快照**：把候选清单 + 8 表计数 + ``export_job.file_path`` 全量落盘，
   便于事后审计与"被删主体反查"。
4. **单事务 + 事务内自校验 + 异常 ROLLBACK**：删除后立即在**同一事务内**复查 8 表计数为 0；
   任一不为 0 → 抛异常 → 整体回滚（不留半清理状态）。
5. **文件清理**：仅删除位于 ``EXPORT_DIR`` 内、且由快照登记过的文件（防目录穿越）；
   越界一律跳过。
6. **不用通配符删除文件**；不删除白名单之外的任何业务行。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Sequence, Tuple

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "backend")
SNAPSHOT = os.path.join(PROJECT, ".workbuddy", "_b8_cleanup_snapshot.json")

#: 白名单正则（本批全部测试账号）
WHITELIST_RE = re.compile(r"^tst[a-z0-9_]{1,16}$")

#: 需清理的业务表（``login_failure_state`` 无 user_id，单独按 username 处理）
USER_TABLES = ("record_tag", "health_record", "health_goal", "user_profile",
               "export_job", "user_session")

RETRY_FILENAME = "cleanup_retry.jsonl"

OUT: List[str] = []


def say(text: str = "") -> None:
    OUT.append(text)
    print(text, flush=True)


def engine():  # noqa: ANN201
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    from app.core.config import load_config

    # ★ 本机事实：``.env.test`` 为占位凭据；连库须显式 override 读 development。
    load_dotenv(os.path.join(BACKEND, ".env.development"), override=True)
    return create_engine(load_config("development")["SQLALCHEMY_DATABASE_URI"])


def export_dir_path() -> str:
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from dotenv import load_dotenv

    from app.core.config import load_config

    load_dotenv(os.path.join(BACKEND, ".env.development"), override=True)
    return os.path.realpath(str(load_config("development")["EXPORT_DIR"]))


def collect_candidates(conn: Any) -> List[Tuple[int, str]]:
    from sqlalchemy import text

    rows = conn.execute(text(
        "SELECT id, username FROM user_account ORDER BY id"
    )).all()
    return [(int(r[0]), str(r[1])) for r in rows]


def guard(candidates: Sequence[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """白名单闸门：任一 tst 前缀候选不匹配正则 → ABORT。"""
    kept: List[Tuple[int, str]] = []
    bad: List[str] = []
    for uid, name in candidates:
        if name.startswith("tst"):
            if WHITELIST_RE.match(name):
                kept.append((uid, name))
            else:
                bad.append(name)
    if bad:
        raise RuntimeError(
            "ABORT：以下账号以 tst 前缀开头但不匹配白名单正则 %s -> %s"
            % (WHITELIST_RE.pattern, bad)
        )
    return kept


def build_snapshot(conn: Any, kept: Sequence[Tuple[int, str]]) -> Dict[str, Any]:
    from sqlalchemy import text

    ids = [uid for uid, _ in kept]
    names = [name for _, name in kept]
    snap: Dict[str, Any] = {"candidates": [{"id": i, "username": n} for i, n in kept],
                            "user_accounts_total": len(
                                collect_candidates(conn)),
                            "counts": {}, "export_files": [],
                            "non_tst_accounts": []}
    if ids:
        holder = ",".join(":i%d" % i for i in range(len(ids)))
        params = {"i%d" % i: v for i, v in enumerate(ids)}
        for table in USER_TABLES:
            snap["counts"][table] = int(conn.execute(text(
                "SELECT COUNT(*) FROM %s WHERE user_id IN (%s)" % (table, holder)
            ), params).scalar() or 0)
        snap["export_files"] = [str(r[0]) for r in conn.execute(text(
            "SELECT file_path FROM export_job WHERE user_id IN (%s)" % holder
        ), params).all() if r[0]]
    else:
        for table in USER_TABLES:
            snap["counts"][table] = 0
    if names:
        holder_u = ",".join(":u%d" % i for i in range(len(names)))
        params_u = {"u%d" % i: v for i, v in enumerate(names)}
        snap["counts"]["login_failure_state"] = int(conn.execute(text(
            "SELECT COUNT(*) FROM login_failure_state WHERE username IN (%s)" % holder_u
        ), params_u).scalar() or 0)
    else:
        snap["counts"]["login_failure_state"] = 0
    snap["counts"]["user_account"] = len(ids)
    snap["non_tst_accounts"] = [
        {"id": int(r[0]), "username": str(r[1])}
        for r in conn.execute(text(
            "SELECT id, username FROM user_account WHERE username NOT LIKE 'tst%' ORDER BY id"
        )).all()
    ]
    # 额外的 tst 前缀残渣（不在候选内，例如仅存在于 login_failure_state）
    snap["stray_login_failure"] = [
        str(r[0]) for r in conn.execute(text(
            "SELECT username FROM login_failure_state WHERE username LIKE 'tst%' ORDER BY username"
        )).all()
    ]
    return snap


def apply_cleanup(engine_obj: Any, kept: Sequence[Tuple[int, str]]) -> Dict[str, int]:
    """单事务删除 + 事务内自校验（失败 ROLLBACK）。"""
    from sqlalchemy import text

    ids = [uid for uid, _ in kept]
    names = [name for _, name in kept]
    counts: Dict[str, int] = {}
    with engine_obj.begin() as conn:
        holder = ",".join(":i%d" % i for i in range(len(ids))) if ids else "NULL"
        params = {"i%d" % i: v for i, v in enumerate(ids)}
        for table in USER_TABLES:
            if ids:
                sql = "DELETE FROM %s WHERE user_id IN (%s)" % (table, holder)
            else:
                sql = "DELETE FROM %s WHERE 1 = 0" % table
            counts[table] = int(conn.execute(text(sql), params).rowcount or 0)
        if names:
            holder_u = ",".join(":u%d" % i for i in range(len(names)))
            params_u = {"u%d" % i: v for i, v in enumerate(names)}
            counts["login_failure_state"] = int(conn.execute(text(
                "DELETE FROM login_failure_state WHERE username IN (%s)" % holder_u
            ), params_u).rowcount or 0)
        else:
            counts["login_failure_state"] = 0
        if ids:
            counts["user_account"] = int(conn.execute(text(
                "DELETE FROM user_account WHERE id IN (%s)" % holder
            ), params).rowcount or 0)
        else:
            counts["user_account"] = 0

        # ── 事务内自校验：8 表目标数据必须全部归零（否则抛异常 → ROLLBACK）──
        residues: List[str] = []
        for table in USER_TABLES:
            if ids:
                n = int(conn.execute(text(
                    "SELECT COUNT(*) FROM %s WHERE user_id IN (%s)" % (table, holder)
                ), params).scalar() or 0)
            else:
                n = 0
            if n:
                residues.append("%s=%d" % (table, n))
        if names:
            n = int(conn.execute(text(
                "SELECT COUNT(*) FROM login_failure_state WHERE username IN (%s)" % holder_u
            ), params_u).scalar() or 0)
            if n:
                residues.append("login_failure_state=%d" % n)
        if ids:
            n = int(conn.execute(text(
                "SELECT COUNT(*) FROM user_account WHERE id IN (%s)" % holder
            ), params).scalar() or 0)
            if n:
                residues.append("user_account=%d" % n)
        if residues:
            raise RuntimeError("事务内自校验失败，已回滚：%s" % residues)
    return counts


def remove_files(paths: Sequence[str]) -> Tuple[int, int, List[str]]:
    base = export_dir_path()
    removed = 0
    skipped = 0
    left: List[str] = []
    for p in paths:
        target = os.path.realpath(str(p))
        try:
            inside = os.path.commonpath([base, target]) == base
        except ValueError:
            inside = False
        if not inside:
            skipped += 1
            continue
        try:
            if os.path.isfile(target):
                os.remove(target)
                removed += 1
        except OSError:
            left.append(os.path.basename(target))
    return removed, skipped, left


def main() -> int:  # noqa: C901
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只报告候选与计数，不动数据（默认）")
    mode.add_argument("--snapshot", action="store_true", help="只落盘清理前快照，不删除")
    mode.add_argument("--apply", action="store_true", help="执行清理（单事务 + 事务内自校验）")
    ap.add_argument("--purge-files", action="store_true",
                    help="额外删除快照登记过的导出文件与空的清理重试登记文件"
                         "（**默认关闭**：数据库清理不触碰文件系统）")
    args = ap.parse_args()

    eng = engine()
    with eng.connect() as conn:
        all_accounts = collect_candidates(conn)
        try:
            kept = guard(all_accounts)
        except RuntimeError as exc:
            say("[ABORT] %s" % exc)
            say("  未删除任何数据。")
            return 3
        snap = build_snapshot(conn, kept)

    say("=" * 72)
    say("  S2 第八批 A-07 · 测试数据清理（白名单 tst* / 显式清单 / 快照 / 单事务）")
    say("=" * 72)
    say("  user_account 总数        : %d" % snap["user_accounts_total"])
    say("  白名单候选（tst 前缀）   : %d 个" % len(kept))
    for uid, name in kept:
        say("      id=%-6d %s" % (uid, name))
    say("  非测试账号（**不得触碰**）: %d 个  %s"
        % (len(snap["non_tst_accounts"]),
           [a["username"] for a in snap["non_tst_accounts"]]))
    say("  清理前 8 表计数          : %s" % json.dumps(snap["counts"], sort_keys=True))
    say("  清理前 export_job 文件   : %d 个" % len(snap["export_files"]))
    if snap["stray_login_failure"]:
        say("  额外 tst 前缀 login_failure_state 残渣: %s" % snap["stray_login_failure"])

    with open(SNAPSHOT, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2, sort_keys=True)
    say("  清理前快照已落盘         : %s" % SNAPSHOT)

    if not args.apply:
        say("")
        say("  [%s] 未执行删除。加 --apply 才会真正清理。"
            % ("dry-run" if not args.snapshot else "snapshot"))
        say("=" * 72)
        return 0

    say("")
    counts = apply_cleanup(eng, kept)
    say("  已提交（单事务）删除计数 : %s" % json.dumps(counts, sort_keys=True))

    left: List[str] = []
    if args.purge_files:
        removed, skipped, left = remove_files(snap["export_files"])
        say("  导出文件清理             : 候选 %d / 删除 %d / 越界跳过 %d / 失败残留 %s"
            % (len(snap["export_files"]), removed, skipped, left))

        retry_path = os.path.join(os.path.dirname(export_dir_path()), RETRY_FILENAME)
        if os.path.isfile(retry_path) and os.path.getsize(retry_path) == 0:
            try:
                os.remove(retry_path)
                say("  已删除空的重试登记文件   : %s" % retry_path)
            except OSError:
                say("  [WARN] 空重试登记文件删除失败: %s" % retry_path)
        else:
            say("  重试登记文件             : %s"
                % ("不存在" if not os.path.isfile(retry_path) else "非空（保留待人工核查）"))
    else:
        retry_path = os.path.join(os.path.dirname(export_dir_path()), RETRY_FILENAME)
        say("  [跳过] 未启用文件清理（**默认不触碰文件系统**）")
        say("         本批登记过的导出文件 : %d 个" % len(snap["export_files"]))
        say("         重试登记文件状态     : %s"
            % ("不存在" if not os.path.isfile(retry_path)
               else ("空文件（无待重试项，属正常）" if os.path.getsize(retry_path) == 0
                     else "非空（含待重试项，**必须**保留待重放）")))
        say("         如需一并删除上述文件，请追加 --purge-files")

    # ── 清理后自证 ──
    from sqlalchemy import text as _sql_text

    with eng.connect() as conn:
        after_tst = int(conn.execute(_sql_text(
            "SELECT COUNT(*) FROM user_account WHERE username LIKE 'tst%'"
        )).scalar() or 0)
        after_non_tst = int(conn.execute(_sql_text(
            "SELECT COUNT(*) FROM user_account WHERE username NOT LIKE 'tst%'"
        )).scalar() or 0)
    say("  清理后 tst 账号残留      : %d（期望 0）" % after_tst)
    say("  清理后非测试账号         : %d（期望 %d，即未减少）"
        % (after_non_tst, len(snap["non_tst_accounts"])))
    say("=" * 72)
    return 0 if (after_tst == 0 and left == []) else 1


if __name__ == "__main__":
    raise SystemExit(main())
