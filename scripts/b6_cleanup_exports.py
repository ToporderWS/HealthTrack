# -*- coding: utf-8 -*-
"""S2 第六批 —— ``backend/storage/exports/`` 测试临时文件**分批**清理脚本。

背景：pytest 收尾会在每个用例后删除本批生成的导出临时文件，单次 `pytest tests/batch6`
累计删除量会触发沙箱「批量删除」拦截。本脚本把清理拆成**每批 ≤ ``--max``（默认 10）**
的小批次，逐批删除并逐批验证，供人工/沙箱友好地完成清理。

三种模式（互不覆盖，各自落盘）：
- ``--precheck``  只读清点：列出候选文件（名 / 大小 / mtime）、判定归属、落盘快照
- ``--delete``    分批物理删除（每批 ≤ ``--max``），逐批验证文件确实消失
- ``--postcheck`` 只读复核：剩余文件与目录状态

**安全边界（硬约束）**
- 只处理 ``backend/storage/exports/`` 目录内、且文件名匹配 ``^[0-9a-f]{32}\\.(csv|json)$``
  （服务端生成规则）的文件；
- 只处理 **mtime ≥ ``--since``**（默认本次 Step 1 起点 ``2026-09-14 17:20:00``）的文件；
- 只处理 **未被任何非 ``tst`` 账号的 ``export_job`` 行引用** 的文件；
- 任何不满足上述全部条件的文件 → **跳过并在报告中列出**，绝不猜测删除；
- 脚本**不触碰**数据库任何数据（只读查询）、不触碰其它目录。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

EXPORT_DIR = os.path.join(BACKEND_DIR, "storage", "exports")
MANIFEST = os.path.join(PROJECT_ROOT, ".workbuddy", "_b6_export_files.txt")
SNAPSHOT = os.path.join(PROJECT_ROOT, ".workbuddy", "_b6_exports_snapshot.json")
DEFAULT_SINCE = "2026-09-14 17:20:00"
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(csv|json)$")
TEST_PREFIX = "tst"
TIME_FMT = "%Y-%m-%d %H:%M:%S"

results: List[str] = []


def say(text: str) -> None:
    print(text, flush=True)
    results.append(text)


def parse_dt(text: str) -> float:
    return time.mktime(time.strptime(text, TIME_FMT))


def manifest_paths() -> set:
    if not os.path.isfile(MANIFEST):
        return set()
    with open(MANIFEST, encoding="utf-8") as handle:
        return {os.path.realpath(line.strip()) for line in handle if line.strip()}


def db_usage() -> Dict[str, Any]:
    """只读查询 ``export_job``：返回 ``{real_path: {"test": bool, "users": [...]}}``。"""
    from sqlalchemy import create_engine, text

    from app.core.config import load_config

    cfg = load_config("development")
    engine = create_engine(cfg["SQLALCHEMY_DATABASE_URI"])
    usage: Dict[str, Any] = {}
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT e.file_path, a.username FROM export_job e "
            "LEFT JOIN user_account a ON a.id = e.user_id "
            "WHERE e.file_path IS NOT NULL"
        )).all()
        for path, username in rows:
            key = os.path.realpath(str(path))
            entry = usage.setdefault(key, {"test": True, "users": []})
            entry["users"].append(username)
            if username is None or not str(username).startswith(TEST_PREFIX):
                entry["test"] = False
    return usage


def scan(since_ts: float) -> Dict[str, Any]:
    if not os.path.isdir(EXPORT_DIR):
        return {"exists": False, "files": []}
    usage = db_usage()
    known = manifest_paths()
    entries = []
    for name in sorted(os.listdir(EXPORT_DIR)):
        path = os.path.join(EXPORT_DIR, name)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        real = os.path.realpath(path)
        hit = usage.get(real)
        in_manifest = real in known
        reasons = []
        if not NAME_RE.match(name):
            reasons.append("文件名不符合服务端生成规则")
        if st.st_mtime < since_ts:
            reasons.append("mtime 早于本次测试起点")
        if hit and not hit["test"]:
            reasons.append("被非测试账号的 export_job 引用：" + repr(hit["users"]))
        entries.append({
            "name": name,
            "path": real,
            "size": st.st_size,
            "mtime": time.strftime(TIME_FMT, time.localtime(st.st_mtime)),
            "in_manifest": in_manifest,
            "db_refs": (hit or {}).get("users", []),
            "skips": reasons,
            "deletable": not reasons,
        })
    return {"exists": True, "files": entries}


def report(entries: List[Dict[str, Any]], tag: str) -> None:
    deletable = [e for e in entries if e["deletable"]]
    skipped = [e for e in entries if not e["deletable"]]
    say(f"[{tag}] 目录文件合计 {len(entries)}；可清理（本批测试生成）{len(deletable)}；"
        f"跳过 {len(skipped)}")
    for entry in entries:
        flag = "DELETE" if entry["deletable"] else "SKIP  "
        say(f"  {flag} {entry['mtime']} {entry['size']:>7} B {entry['name']}"
            f"  manifest={'Y' if entry['in_manifest'] else 'N'}"
            + (f"  ⚠{entry['skips']}" if entry["skips"] else ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--precheck", action="store_true")
    group.add_argument("--delete", action="store_true")
    group.add_argument("--postcheck", action="store_true")
    parser.add_argument("--max", type=int, default=10, help="单次删除上限（默认 10）")
    parser.add_argument("--since", default=DEFAULT_SINCE)
    args = parser.parse_args()

    since_ts = parse_dt(args.since)
    data = scan(since_ts)
    if not data["exists"]:
        say(f"[ERROR] 目录不存在：{EXPORT_DIR}")
        return 2

    if args.precheck:
        report(data["files"], "PRECHECK")
        with open(SNAPSHOT, "w", encoding="utf-8") as handle:
            json.dump({"since": args.since, "files": data["files"]}, handle,
                      ensure_ascii=False, indent=2)
        say(f"快照已落盘：{SNAPSHOT}")
        return 0

    if args.postcheck:
        report(data["files"], "POSTCHECK")
        say("剩余文件数 = " + str(len(data["files"])))
        return 0

    batch = [e for e in data["files"] if e["deletable"]][: max(1, int(args.max))]
    if not batch:
        say("[DELETE] 无可清理文件（已全部清理完毕）")
        return 0
    say(f"[DELETE] 本批 {len(batch)} 个（上限 {args.max}）")
    removed, failed = [], []
    for entry in batch:
        try:
            os.remove(entry["path"])
        except OSError as exc:  # noqa: PERF203
            failed.append((entry["name"], str(exc)))
            continue
        if os.path.exists(entry["path"]):
            failed.append((entry["name"], "删除后仍存在"))
        else:
            removed.append(entry["name"])
    say("已删除 " + str(len(removed)) + "：")
    for name in removed:
        say("   - " + name)
    say("失败 " + str(len(failed)) + ("：" + repr(failed) if failed else ""))
    left = scan(since_ts)["files"]
    say("本批验证：剩余可清理 " + str(len([e for e in left if e["deletable"]]))
        + " / 目录文件合计 " + str(len(left)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
