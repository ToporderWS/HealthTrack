# -*- coding: utf-8 -*-
"""S2 第六批测试数据清理（**DB 侧**）：仅 4 个 ``tst`` 测试账号及其关联数据。

安全纪律（与既有清理脚本一致）：
- 三模式分离：``--precheck`` / ``--delete`` / ``--postcheck``；
- 目标账号为**精确白名单**（不使用 ``LIKE`` 泛匹配删除）；
- **单事务** + **事务内自校验** + 异常 ``ROLLBACK``；
- 清理前全行快照落盘（JSON）；
- 空集合一律返回恒假条件 ``1=0``（避免非法 ``IN ()``）；
- 只做 DML，**不做任何 DDL / migration**，不触碰非测试账号数据。

用法：
    python scripts/b6_cleanup_testdata.py --precheck
    python scripts/b6_cleanup_testdata.py --delete
    python scripts/b6_cleanup_testdata.py --postcheck
"""
import argparse
import datetime
import json
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "backend")
sys.path.insert(0, BACKEND)

#: 精确白名单（仅清理这 4 个账号，不做前缀泛匹配）
TARGET_USERNAMES = ("tstb6edgea", "tstb6edgeb", "tstb6edgez1", "tstb6edgez2")

#: 以 ``user_id`` 关联到账号的表
USER_SCOPED_TABLES = ("export_job", "health_goal", "health_record",
                      "record_tag", "user_profile", "user_session")

#: 以 ``username`` 关联的表（主键为 username，无 user_id）
USERNAME_SCOPED_TABLES = ("login_failure_state",)

#: 全部业务表（用于前后结构/行数对照）
ALL_TABLES = ("user_account", "user_profile", "health_record", "record_tag",
              "health_goal", "user_session", "login_failure_state", "export_job")

SNAPSHOT = os.path.join(PROJECT, ".workbuddy", "_b3_cleanup_snapshot.json")
OUT_DIR = os.path.join(PROJECT, ".workbuddy")

LINES = []


def say(text=""):
    print(text, flush=True)
    LINES.append(str(text))


def dump(name):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(LINES) + "\n")
    return path


def engine_of():
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BACKEND, ".env.development"), override=True)
    from sqlalchemy import create_engine

    from app.core.config import load_config

    cfg = load_config("development")
    url = cfg.get("SQLALCHEMY_DATABASE_URI") or cfg.get("DATABASE_URL")
    return create_engine(url)


def placeholders(names, prefix):
    items = [":%s%d" % (prefix, i) for i in range(len(names))]
    params = {"%s%d" % (prefix, i): v for i, v in enumerate(names)}
    return items, params


def where_ids(ids):
    """空集合 -> 恒假条件（避免非法 ``IN ()``）。"""
    if not ids:
        return "1 = 0", {}
    return "user_id IN (%s)" % ", ".join(":i%d" % i for i in range(len(ids))), \
        {"i%d" % i: v for i, v in enumerate(ids)}


def read_state(conn):
    from sqlalchemy import text as sa_text

    items, params = placeholders(TARGET_USERNAMES, "u")
    state = {"tables": {}, "accounts": [], "scoped_counts": {}, "non_test_jobs": 0,
             "total_jobs": 0, "structure": {}}
    for table in ALL_TABLES:
        state["tables"][table] = int(conn.execute(
            sa_text("SELECT COUNT(*) FROM `%s`" % table)).scalar() or 0)
    for row in conn.execute(sa_text(
            "SELECT id, username FROM user_account WHERE username IN (%s) ORDER BY id"
            % ", ".join(items)), params).all():
        state["accounts"].append({"id": int(row[0]), "username": row[1]})
    ids = [a["id"] for a in state["accounts"]]
    cond, iparams = where_ids(ids)
    for table in USER_SCOPED_TABLES:
        state["scoped_counts"][table] = int(conn.execute(
            sa_text("SELECT COUNT(*) FROM `%s` WHERE %s" % (table, cond)), iparams).scalar() or 0)
    for table in USERNAME_SCOPED_TABLES:
        ucond, uparams = placeholders(TARGET_USERNAMES, "s")
        state["scoped_counts"][table] = int(conn.execute(
            sa_text("SELECT COUNT(*) FROM `%s` WHERE username IN (%s)"
                    % (table, ", ".join(ucond))), uparams).scalar() or 0)
    state["total_jobs"] = state["tables"]["export_job"]
    state["non_test_jobs"] = int(conn.execute(sa_text(
        "SELECT COUNT(*) FROM export_job j LEFT JOIN user_account a ON a.id = j.user_id "
        "WHERE a.username IS NULL OR a.username NOT IN (%s)"
        % ", ".join(items)), params).scalar() or 0)
    struct = {}
    for table in ALL_TABLES:
        cols = conn.execute(sa_text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t"), {"t": table}).scalar()
        idx = conn.execute(sa_text(
            "SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = :t"), {"t": table}).scalar()
        struct[table] = {"columns": int(cols or 0), "indexes": int(idx or 0)}
    state["structure"] = struct
    return state


def print_state(state, title):
    say("── %s ──" % title)
    say("  表行数：" + ", ".join("%s=%d" % (t, state["tables"][t]) for t in ALL_TABLES))
    say("  测试账号：" + (", ".join("%s(id=%d)" % (a["username"], a["id"])
                                  for a in state["accounts"]) or "（无）"))
    say("  测试账号关联行：" + ", ".join("%s=%d" % (t, state["scoped_counts"][t])
                                        for t in state["scoped_counts"]))
    say("  export_job 合计 = %d；其中**非测试账号** = %d（必须 0）"
        % (state["total_jobs"], state["non_test_jobs"]))
    say("  表结构指纹：" + ", ".join(
        "%s(%dc/%di)" % (t, state["structure"][t]["columns"], state["structure"][t]["indexes"])
        for t in ALL_TABLES))


def mode_precheck():
    from sqlalchemy import text as sa_text

    eng = engine_of()
    with eng.connect() as conn:
        state = read_state(conn)
        say("=" * 74)
        say("B3-2 清理前只读确认（DB 侧）  %s"
            % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        say("=" * 74)
        print_state(state, "清理前")
        say("")
        names = [a["username"] for a in state["accounts"]]
        unknown = [n for n in names if n not in TARGET_USERNAMES]
        say("  白名单判定：命中 %d 个（%s）；白名单外 %d 个 %s"
            % (len(names), ", ".join(names) or "-", len(unknown), unknown))
        if unknown:
            say("  [STOP] 存在白名单外账号 -> 不允许删除")
        say("  非测试账号 export_job 必须为 0 = %s" % (state["non_test_jobs"] == 0))
        say("  账号总数（清理后应为 0）：%d" % state["tables"]["user_account"])
    with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    say("")
    say("  快照落盘：%s" % SNAPSHOT)
    path = dump("_b3_clean_pre.txt")
    say("  证据落盘：%s" % path)
    return 0


def mode_delete():
    from sqlalchemy import text as sa_text

    eng = engine_of()
    with eng.connect() as conn:
        state = read_state(conn)
        say("=" * 74)
        say("B3-2 执行清理（DB 侧，单事务）  %s"
            % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        say("=" * 74)
        print_state(state, "清理前")
        names = [a["username"] for a in state["accounts"]]
        unknown = [n for n in names if n not in TARGET_USERNAMES]
        if unknown or not names:
            say("  [ABORT] 白名单外账号 %s 或白名单命中 0 个 -> 不执行任何删除"
                % (unknown,))
            dump("_b3_clean_delete.txt")
            return 3
        say("  将清理 %d 个白名单账号：%s" % (len(names), ", ".join(names)))
        if state["non_test_jobs"] != 0:
            say("  [ABORT] 存在非测试账号 export_job -> 不执行任何删除")
            dump("_b3_clean_delete.txt")
            return 3

    ids = [a["id"] for a in state["accounts"]]
    deleted = {}
    with eng.connect() as conn:
        trans = conn.begin()
        try:
            cond, iparams = where_ids(ids)
            for table in USER_SCOPED_TABLES:
                res = conn.execute(sa_text("DELETE FROM `%s` WHERE %s" % (table, cond)),
                                   iparams)
                deleted[table] = int(res.rowcount or 0)
            ucond, uparams = placeholders(TARGET_USERNAMES, "s")
            for table in USERNAME_SCOPED_TABLES:
                res = conn.execute(sa_text("DELETE FROM `%s` WHERE username IN (%s)"
                                           % (table, ", ".join(ucond))), uparams)
                deleted[table] = int(res.rowcount or 0)
            res = conn.execute(sa_text("DELETE FROM user_account WHERE id IN (%s)"
                                       % ", ".join(":i%d" % i for i in range(len(ids)))),
                               {"i%d" % i: v for i, v in enumerate(ids)})
            deleted["user_account"] = int(res.rowcount or 0)

            # ── 事务内自校验
            left = int(conn.execute(sa_text(
                "SELECT COUNT(*) FROM user_account WHERE username IN (%s)"
                % ", ".join(placeholders(TARGET_USERNAMES, "u")[0])),
                placeholders(TARGET_USERNAMES, "u")[1]).scalar() or 0)
            residue = {}
            for table in USER_SCOPED_TABLES:
                residue[table] = int(conn.execute(
                    sa_text("SELECT COUNT(*) FROM `%s` WHERE %s" % (table, cond)),
                    iparams).scalar() or 0)
            for table in USERNAME_SCOPED_TABLES:
                residue[table] = int(conn.execute(
                    sa_text("SELECT COUNT(*) FROM `%s` WHERE username IN (%s)"
                            % (table, ", ".join(ucond))), uparams).scalar() or 0)

            say("  逐表删除行数：" + ", ".join("%s=%d" % (k, v) for k, v in deleted.items()))
            say("  事务内自校验：残留账号 = %d；关联残留 = %s"
                % (left, ", ".join("%s=%d" % (k, v) for k, v in residue.items())))
            if left != 0 or any(residue.values()):
                trans.rollback()
                say("  [ROLLBACK] 事务内自校验未通过 -> 已回滚，未产生任何变更")
                dump("_b3_clean_delete.txt")
                return 4
            trans.commit()
            say("  [COMMITTED] 单事务提交成功")
        except Exception as exc:  # noqa: BLE001
            trans.rollback()
            say("  [ROLLBACK] 异常：%s -> 已回滚" % exc)
            dump("_b3_clean_delete.txt")
            return 5

    with eng.connect() as conn:
        after = read_state(conn)
        print_state(after, "清理后")
        say("")
        say("  结构指纹一致（清理前 vs 清理后）= %s"
            % (after["structure"] == state["structure"]))
        say("  非测试账号 export_job = %d（必须 0）" % after["non_test_jobs"])
    path = dump("_b3_clean_delete.txt")
    say("  证据落盘：%s" % path)
    return 0


def mode_postcheck():
    eng = engine_of()
    with eng.connect() as conn:
        state = read_state(conn)
        say("=" * 74)
        say("B3-2 清理后只读复核（DB 侧）  %s"
            % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        say("=" * 74)
        print_state(state, "清理后")
        say("")
        say("  4 个 tst 测试账号残留数 = %d（必须 0）" % len(state["accounts"]))
        say("  测试账号 export_job 合计 = %d（必须 0）"
            % state["scoped_counts"]["export_job"])
        say("  export_job 全表行数 = %d" % state["total_jobs"])
        say("  非测试账号 export_job = %d（必须 0）" % state["non_test_jobs"])
        say("  tst 前缀账号（含未在白名单内的）总数 = %d"
            % int(conn.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM user_account WHERE username LIKE 'tst%'")).scalar() or 0))
        path = dump("_b3_clean_post.txt")
        say("  证据落盘：%s" % path)
    return 0


def main():
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--precheck", action="store_true")
    group.add_argument("--delete", action="store_true")
    group.add_argument("--postcheck", action="store_true")
    args = ap.parse_args()
    if args.precheck:
        return mode_precheck()
    if args.delete:
        return mode_delete()
    return mode_postcheck()


if __name__ == "__main__":
    sys.exit(main())
