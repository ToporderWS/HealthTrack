# -*- coding: utf-8 -*-
"""S2 第七批测试数据清理（**白名单 + 单事务 + 事务内自校验 + 前置快照**）。

安全口径：
- 唯一允许清理的账号集合 = :data:`WHITELIST`（本批自建 4 个 ``tst`` 测试账号）。
  实际命中集合必须 **⊆ 白名单**，否则直接 ABORT（不执行任何写操作）。
- 三模式分离：``--precheck``（只读快照）/ ``--delete``（物理 DELETE，单事务）/ ``--postcheck``（全表行数 + 残留自证）。
- 清理前把两账号在 8 张表的**全部行**快照落盘（审计留痕）。
- 事务内先按 id 聚合再逐表 DELETE；异常 → ROLLBACK 并中止。
- 本脚本**保留**作审计留痕。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\b7_cleanup_testdata.py --precheck
    backend\\.venv\\Scripts\\python.exe scripts\\b7_cleanup_testdata.py --delete
    backend\\.venv\\Scripts\\python.exe scripts\\b7_cleanup_testdata.py --postcheck
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "backend")

#: **唯一**允许清理的测试账号白名单（本批 Acceptance 自建）
WHITELIST = ("tstb7smokea", "tstb7smokeb", "tstb7edgea", "tstb7edgeb")

#: 有 ``user_id`` 列的表（按 user_id 物理 DELETE）
USER_TABLES = ("record_tag", "health_record", "health_goal", "export_job",
               "user_session", "user_profile")
#: 全表清单（postcheck 行数自证；``login_failure_state`` 主键为 username）
ALL_TABLES = ("user_account", "user_profile", "health_record", "record_tag",
              "health_goal", "user_session", "login_failure_state", "export_job")


def engine():  # noqa: ANN201
    sys.path.insert(0, BACKEND)
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    from app.core.config import load_config

    # ★ 本机事实：``.env.test`` 的 DB 凭据是占位值；显式 override 载入 .env.development
    load_dotenv(os.path.join(BACKEND, ".env.development"), override=True)
    return create_engine(load_config("development")["SQLALCHEMY_DATABASE_URI"])


def rows(conn, sql: str, params: Dict[str, Any]) -> List[Any]:
    from sqlalchemy import text

    return conn.execute(text(sql), params).all()


def snapshot(conn, ids: List[int], usernames: List[str]) -> str:
    """把白名单账号在 8 张表的**全部行**快照落盘（清理前审计留痕）。"""
    lines: List[str] = []
    for table in USER_TABLES:
        if not ids:
            lines.append("[%s] (无命中账号，跳过)" % table)
            continue
        holder = ",".join(":i%d" % i for i in range(len(ids)))
        params = {"i%d" % i: v for i, v in enumerate(ids)}
        for r in rows(conn, "SELECT * FROM %s WHERE user_id IN (%s) ORDER BY id"
                           % (table, holder), params):
            lines.append("[%s] %s" % (table, tuple(r)))
    if usernames:
        holder = ",".join(":u%d" % i for i in range(len(usernames)))
        params = {"u%d" % i: n for i, n in enumerate(usernames)}
        for r in rows(conn, "SELECT * FROM login_failure_state WHERE username IN (%s)"
                           % holder, params):
            lines.append("[login_failure_state] %s" % (tuple(r),))
        for r in rows(conn, "SELECT id, username, created_at FROM user_account "
                            "WHERE id IN (%s)"
                            % (",".join(":i%d" % i for i in range(len(ids))) if ids else "NULL"),
                      {"i%d" % i: v for i, v in enumerate(ids)}):
            lines.append("[user_account] %s" % (tuple(r),))
    return "\n".join(lines)


def table_counts(conn) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for table in ALL_TABLES:
        out[table] = int(rows(conn, "SELECT COUNT(*) FROM %s" % table, {})[0][0])
    return out


def resolve_ids(conn) -> "tuple[List[int], List[str]]":
    holder = ",".join(":u%d" % i for i in range(len(WHITELIST)))
    params = {"u%d" % i: n for i, n in enumerate(WHITELIST)}
    got = rows(conn, "SELECT id, username FROM user_account WHERE username IN (%s) "
                     "ORDER BY id" % holder, params)
    ids = [int(r[0]) for r in got]
    names = [str(r[1]) for r in got]
    outside = [n for n in names if n not in WHITELIST]
    if outside:
        raise RuntimeError("ABORT：命中白名单外账号 %s" % outside)
    return ids, names


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--precheck", action="store_true")
    g.add_argument("--delete", action="store_true")
    g.add_argument("--postcheck", action="store_true")
    args = ap.parse_args()

    from sqlalchemy import text

    eng = engine()
    out: List[str] = []
    rc = 0

    with eng.connect() as conn:
        ids, names = resolve_ids(conn)
        out.append("白名单 = %s" % (list(WHITELIST),))
        out.append("实际命中 = %s（ids=%s）" % (names, ids))
        out.append("白名单校验：实际 ⊆ 白名单 -> %s" % (set(names) <= set(WHITELIST),))

        if args.precheck:
            out.append("")
            out.append("=== 清理前全行快照 ===")
            out.append(snapshot(conn, ids, names))
            out.append("")
            out.append("=== 清理前全表行数 ===")
            for k, v in table_counts(conn).items():
                out.append("  %-22s %d" % (k, v))

        elif args.delete:
            if not ids:
                out.append("无命中账号，无需清理（空集合保护，不执行 DELETE）")
            else:
                out.append("")
                out.append("=== 单事务物理 DELETE ===")
                counts: Dict[str, int] = {}
                try:
                    with eng.begin() as tx:
                        # 事务内自校验：再次确认命中集合仍在白名单内
                        check = rows(tx, "SELECT username FROM user_account WHERE id IN (%s)"
                                     % ",".join(":i%d" % i for i in range(len(ids))),
                                     {"i%d" % i: v for i, v in enumerate(ids)})
                        names2 = [str(r[0]) for r in check]
                        if not set(names2) <= set(WHITELIST):
                            raise RuntimeError("事务内校验失败：%s" % names2)

                        holder = ",".join(":i%d" % i for i in range(len(ids)))
                        params = {"i%d" % i: v for i, v in enumerate(ids)}
                        for table in USER_TABLES:
                            res = tx.execute(
                                text(
                                    "DELETE FROM %s WHERE user_id IN (%s)" % (table, holder)),
                                params)
                            counts[table] = int(res.rowcount or 0)
                        uph = ",".join(":u%d" % i for i in range(len(WHITELIST)))
                        uparams = {"u%d" % i: n for i, n in enumerate(WHITELIST)}
                        res = tx.execute(
                            text(
                                "DELETE FROM login_failure_state WHERE username IN (%s)" % uph),
                            uparams)
                        counts["login_failure_state"] = int(res.rowcount or 0)
                        res = tx.execute(
                            text(
                                "DELETE FROM user_account WHERE id IN (%s)" % holder), params)
                        counts["user_account"] = int(res.rowcount or 0)
                    for k, v in counts.items():
                        out.append("  DELETE %-22s %d 行" % (k, v))
                    out.append("事务已提交")
                except Exception as exc:  # noqa: BLE001
                    out.append("!! 事务异常，已 ROLLBACK：%s" % exc)
                    rc = 1

        elif args.postcheck:
            out.append("")
            out.append("=== 清理后全表行数 ===")
            for k, v in table_counts(conn).items():
                out.append("  %-22s %d" % (k, v))
            left = table_counts(conn)
            out.append("")
            out.append("=== 残留自证 ===")
            out.append("  白名单账号残留 = %s（期望 0）" % len(names))
            tst = rows(conn, "SELECT COUNT(*) FROM user_account WHERE username LIKE 'tst%%'",
                       {})[0][0]
            out.append("  全库 tst 前缀账号 = %d（期望 0）" % int(tst))
            tst_jobs = rows(conn, "SELECT COUNT(*) FROM export_job e JOIN user_account a "
                                  "ON a.id = e.user_id WHERE a.username LIKE 'tst%%'", {})[0][0]
            out.append("  tst 账号遗留导出任务 = %d（期望 0）" % int(tst_jobs))
            out.append("  8 表合计行数 = %d" % sum(left.values()))

    text = "\n".join(str(x) for x in out)
    print(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
