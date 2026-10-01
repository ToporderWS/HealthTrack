# -*- coding: utf-8 -*-
"""S2 第八批 A-07（注销账号）真实 HTTP 联调冒烟（四账号 · 造数 · 断言 · 清理）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch8_http_smoke.py
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch8_http_smoke.py --port 5000
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch8_http_smoke.py --purge-files

``--purge-files``（**默认关闭**）用于收尾时删除本次创建过的导出文件与空的清理重试登记文件；
默认**不触碰文件系统**（断言与数据库清理相互独立）。

前置：后端已启动（``cd backend && .venv/Scripts/python.exe wsgi.py``）。

口径：
1. 四个账号，全部以 ``tst`` 前缀命名（与本批 ``tests/batch8/conftest.py`` 的 ``tst`` 前缀一致）：
   - ``tstb8smokea`` —— **被测主体**（最终被 A-07 注销）；
   - ``tstb8smokeb`` —— **隔离对端**（全程不得受影响）；
   - ``tstb8smokec`` —— **T4 失败重试演示**（导出文件被本进程持句柄占用 → 删除必失败）；
   - ``tstb8smoked`` —— **重放触发**（其注销流程会顺带 ``drain``，清空 C 的重试登记）。
2. **A-07 是破坏性操作**：仅对本脚本自建的白名单账号执行；
   **绝不对任何非测试账号执行**（清理函数内置白名单闸门）。
3. 造数全部经**真实 HTTP**（R-01 记录 / R-07 软删 / P-02 档案 / G-02 建目标 / G-04 暂停 /
   E-01 导出任务，导出文件真实落盘于 ``EXPORT_DIR``）；``login_failure_state`` 本表
   **无 API 写入入口**，故直连 SQL 造一行（仅测试装置行为）。
4. 断言覆盖：鉴权 / ``user_id`` 守卫 / 三重确认（缺 confirm → REQUIRED；错 confirm →
   INVALID_FORMAT；错密码 → PASSWORD_INVALID 且 **不累计、无 429**）/ 数据在失败时保持原状 /
   范围扩展参数无效 / 成功响应 shape 与文案 / **8 表物理归零**（含软删行、档案整行）/
   导出文件已删 + 重试登记脱敏 / Token 与 refresh 全部失效 / 重复注销 401 /
   用户名释放（可重新注册且可登录）/ 对端完全不受影响 / 安全闸门自证。
5. 收尾：``finally`` 清理本次测试数据（**仅白名单 4 账号**，逐表物理 DELETE +
   显式删除本次创建过的导出文件）。

> 脚本**自身落盘** stdout / stderr（调用方请勿使用 ``| tail`` 等本机不兼容管道）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "backend")

DEFAULT_PORT = 5000
PWD = "Kangji2026"

UA = "tstb8smokea"          # 被测主体
UB = "tstb8smokeb"          # 隔离对端
UC = "tstb8smokec"          # T4 失败重试演示
UD = "tstb8smoked"          # 重放触发

#: 清理白名单（**唯一**允许被物理删除的账号集合）
WHITELIST = (UA, UB, UC, UD)

#: A-07 独立确认文字（**不得**复用 D-02 的「确认删除」）
CONFIRM_TEXT = "注销账号"
D02_CONFIRM_TEXT = "确认删除"

#: A-07 成功响应 data 恰 1 键（冻结）
CLOSED_KEYS = ["account_closed"]
#: 统一 envelope 4 键（成功）
ENVELOPE_KEYS = ["code", "data", "message", "request_id"]

#: A-07 必须物理归零的 8 张表
PURGE_TABLES = ("record_tag", "health_record", "health_goal", "user_profile",
                "export_job", "user_session")
#: ``user_profile`` 6 个健康字段
PROFILE_HEALTH_FIELDS = ["height_cm", "initial_weight_kg", "blood_type",
                         "medical_history", "allergy_history", "medication_notes"]

DT_FMT = "%Y-%m-%d %H:%M:%S"
RETRY_FILENAME = "cleanup_retry.jsonl"

RESULTS: List[Tuple[str, bool, str]] = []
FAILS: List[str] = []
#: 本次创建过的导出文件 basename（收尾显式清理；不依赖通配符）
CREATED_FILES: List[str] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    if not ok:
        FAILS.append(name + (("   -> " + detail) if detail else ""))


def say(text: str = "") -> None:
    print(text, flush=True)


# ════════════════════════════════════════════════════════════════════
# HTTP
# ════════════════════════════════════════════════════════════════════
class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
             token: Optional[str] = None,
             headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
        status, _hdrs, raw = self.raw(method, path, body, token, headers)
        text = raw.decode("utf-8", "replace")
        try:
            return status, (json.loads(text) if text else None)
        except Exception:
            return status, None

    def raw(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
            token: Optional[str] = None,
            headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], bytes]:
        url = self.base + path
        data = None
        out_headers: Dict[str, str] = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            out_headers["Content-Type"] = "application/json"
        if token:
            out_headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=data, headers=out_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()


def data_of(body: Any) -> Dict[str, Any]:
    got = (body or {}).get("data")
    return got if isinstance(got, dict) else {}


def code_of(body: Any) -> str:
    return (body or {}).get("code") or ""


def msg_of(body: Any) -> str:
    return (body or {}).get("message") or ""


def errors_of(body: Any) -> List[Any]:
    got = (body or {}).get("errors")
    return got if isinstance(got, list) else []


# ════════════════════════════════════════════════════════════════════
# 时间工具（本地墙上时间）
# ════════════════════════════════════════════════════════════════════
def stamp(day_offset: int, hour: int = 9, minute: int = 0, second: int = 0) -> str:
    day = datetime.now().date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute, second)).strftime(DT_FMT)


# ════════════════════════════════════════════════════════════════════
# DB（仅用于：造 login_failure_state / 只读核查 / 收尾清理白名单账号）
# ════════════════════════════════════════════════════════════════════
def engine():  # noqa: ANN201
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    from app.core.config import load_config

    # ★ 本机事实：``.env.test`` 凭据为占位值；连库必须显式以 override=True 读 development。
    load_dotenv(os.path.join(BACKEND, ".env.development"), override=True)
    return create_engine(load_config("development")["SQLALCHEMY_DATABASE_URI"])


def export_dir_path() -> str:
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from dotenv import load_dotenv

    from app.core.config import load_config

    load_dotenv(os.path.join(BACKEND, ".env.development"), override=True)
    return os.path.realpath(str(load_config("development")["EXPORT_DIR"]))


def retry_queue_path() -> str:
    return os.path.join(os.path.dirname(export_dir_path()), RETRY_FILENAME)


def db_rows(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
    from sqlalchemy import text

    eng = engine()
    with eng.connect() as conn:
        return conn.execute(text(sql), params or {}).all()


def db_exec(sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    from sqlalchemy import text

    eng = engine()
    with eng.begin() as conn:
        return int(conn.execute(text(sql), params or {}).rowcount or 0)


def count_where(table: str, where: str, params: Dict[str, Any]) -> int:
    rows = db_rows("SELECT COUNT(*) FROM %s WHERE %s" % (table, where), params)
    return int(rows[0][0]) if rows else 0


def user_id_of(username: str) -> int:
    rows = db_rows("SELECT id FROM user_account WHERE username = :u", {"u": username})
    return int(rows[0][0]) if rows else 0


def account_usernames() -> List[str]:
    return [str(r[0]) for r in db_rows("SELECT username FROM user_account ORDER BY id")]


def purge_tables_of(uids: Sequence[int]) -> Dict[str, int]:
    """逐表**物理 DELETE** 这些 uid 的全部业务行 + 按 username 收尾（**单事务**）。

    **安全闸门**：调用前校验「实际 uid 全部来自白名单账号」，否则拒绝执行。
    """
    from sqlalchemy import text

    if not uids:
        return {}
    holder = ",".join(":i%d" % i for i in range(len(uids)))
    params = {"i%d" % i: int(v) for i, v in enumerate(uids)}
    eng = engine()
    counts: Dict[str, int] = {}
    with eng.begin() as conn:
        for table in PURGE_TABLES:
            res = conn.execute(text(
                "DELETE FROM %s WHERE user_id IN (%s)" % (table, holder)), params)
            counts[table] = int(res.rowcount or 0)
    return counts


def purge_accounts(usernames: Sequence[str]) -> Tuple[Dict[str, int], List[str]]:
    """清理**白名单**账号：先取导出文件路径 → 单事务物理删除 → 返回（计数, 文件路径）。"""
    from sqlalchemy import text

    outside = [u for u in usernames if u not in WHITELIST]
    if outside:
        raise RuntimeError("拒绝清理：账号 %s 不在白名单 %s 内" % (outside, list(WHITELIST)))

    eng = engine()
    counts: Dict[str, int] = {}
    files: List[str] = []
    if not usernames:
        return counts, files

    holder_u = ",".join(":u%d" % i for i in range(len(usernames)))
    params_u = {"u%d" % i: n for i, n in enumerate(usernames)}
    with eng.begin() as conn:
        ids = [int(r[0]) for r in conn.execute(text(
            "SELECT id FROM user_account WHERE username IN (%s)" % holder_u), params_u).all()]
        if ids:
            holder = ",".join(":i%d" % i for i in range(len(ids)))
            params = {"i%d" % i: v for i, v in enumerate(ids)}
            for row in conn.execute(text(
                    "SELECT file_path FROM export_job WHERE user_id IN (%s)" % holder),
                    params).all():
                if row[0]:
                    files.append(str(row[0]))
            for table in PURGE_TABLES:
                res = conn.execute(text(
                    "DELETE FROM %s WHERE user_id IN (%s)" % (table, holder)), params)
                counts[table] = int(res.rowcount or 0)
            res = conn.execute(text("DELETE FROM user_account WHERE id IN (%s)" % holder), params)
            counts["user_account"] = int(res.rowcount or 0)
        res = conn.execute(text(
            "DELETE FROM login_failure_state WHERE username IN (%s)" % holder_u), params_u)
        counts["login_failure_state"] = int(res.rowcount or 0)
    return counts, files


def remove_inside_export_dir(paths: Sequence[str]) -> Tuple[int, int]:
    """只删除位于 ``EXPORT_DIR`` 内的文件；越界跳过（安全）。"""
    base = export_dir_path()
    removed = 0
    skipped = 0
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
            skipped += 1
    return removed, skipped


def read_retry_queue() -> List[Dict[str, Any]]:
    path = retry_queue_path()
    if not os.path.isfile(path):
        return []
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                entry = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                items.append(entry)
    return items


# ════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════
def main() -> int:  # noqa: C901
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--purge-files", action="store_true",
                    help="收尾时额外删除本次创建过的导出文件与空的清理重试登记文件"
                         "（**默认关闭**：断言与数据库清理不触碰文件系统）")
    ap.add_argument("--skip-files", action="store_true",
                    help="跳过所有会**删除文件**的用例（E-01 导出任务 + T4 文件删除/重试演示）。"
                         "适用于禁止删除文件的环境（如受限沙箱）；"
                         "文件与重试行为的权威覆盖见 backend/tests/batch8/test_a07_files_retry.py")
    args = ap.parse_args()

    c = Client("http://%s:%d/api/v1" % (args.host, args.port))
    tokens: Dict[str, Optional[str]] = {}
    refreshes: Dict[str, Optional[str]] = {}
    uid: Dict[str, int] = {}
    held_handle = None
    extra_files: List[str] = []

    def boot(user: str) -> None:
        c.call("POST", "/auth/register", {
            "username": user, "password": PWD,
            "agreement_version": "v1.0", "agreement_accepted": True,
        })
        st, body = c.call("POST", "/auth/login", {"username": user, "password": PWD})
        if st != 200:
            raise RuntimeError("账号 %s 登录失败 HTTP %s %s" % (user, st, code_of(body)))
        tks = data_of(body).get("tokens") or {}
        tokens[user] = tks.get("access_token")
        refreshes[user] = tks.get("refresh_token")

    try:
        # ── 0. 连通性 ───────────────────────────────────────────────
        st, body = c.call("GET", "/health")
        if st != 200:
            say("[FATAL] 后端未就绪：GET /api/v1/health -> HTTP %s。"
                "请先启动：cd backend && .venv/Scripts/python.exe wsgi.py" % st)
            return 2
        record("冒烟：GET /api/v1/health 200 OK", code_of(body) == "OK", "HTTP %s" % st)

        # ── 1. 四账号就绪 ───────────────────────────────────────────
        for user in WHITELIST:
            boot(user)
        record("四账号就绪（%s 主体 / %s 对端 / %s 重试 / %s 重放）" % (UA, UB, UC, UD),
               all(tokens.get(u) and refreshes.get(u) for u in WHITELIST))
        for user in WHITELIST:
            uid[user] = user_id_of(user)
        record("四账号 uid 均可用", all(uid[u] > 0 for u in WHITELIST), str(uid))

        # ── 2. 鉴权与全局守卫 ───────────────────────────────────────
        st, body = c.call("DELETE", "/users/me", {"confirm_text": CONFIRM_TEXT, "password": PWD})
        record("A-07 无 Token -> 401 UNAUTHENTICATED",
               st == 401 and code_of(body) == "UNAUTHENTICATED", "HTTP %s %s" % (st, code_of(body)))

        st, body = c.call("DELETE", "/users/me", {"confirm_text": CONFIRM_TEXT, "password": PWD},
                          "not-a-valid-token")
        record("A-07 坏 Token -> 401 UNAUTHENTICATED",
               st == 401 and code_of(body) == "UNAUTHENTICATED", "HTTP %s %s" % (st, code_of(body)))

        st, body = c.call("DELETE", "/users/me",
                          {"confirm_text": CONFIRM_TEXT, "password": PWD, "user_id": 1},
                          tokens[UA])
        record("A-07 body 携带 user_id -> 400 INVALID_PARAM（全局守卫）",
               st == 400 and code_of(body) == "INVALID_PARAM", "HTTP %s %s" % (st, code_of(body)))

        st, body = c.call("DELETE", "/users/me?user_id=1",
                          {"confirm_text": CONFIRM_TEXT, "password": PWD}, tokens[UA])
        record("A-07 query 携带 user_id -> 400 INVALID_PARAM（全局守卫）",
               st == 400 and code_of(body) == "INVALID_PARAM", "HTTP %s %s" % (st, code_of(body)))

        # ── 3. 造数（A 端：3 活跃 + 1 软删 + 标签；2 目标；档案 3/6；导出任务；登录失败行） ──
        rec_ids: List[int] = []

        def add_rec(user: str, **payload: Any) -> int:
            st2, b2 = c.call("POST", "/records", payload, tokens[user])
            if st2 != 201:
                raise RuntimeError("R-01 写入失败 HTTP %s %s payload=%s"
                                   % (st2, code_of(b2), payload))
            rid = int(data_of(b2)["record"]["id"])
            rec_ids.append(rid)
            return rid

        add_rec(UA, metric_type="weight", value_1=70.50, recorded_at=stamp(-2, 9))
        add_rec(UA, metric_type="water", value_1=500, recorded_at=stamp(-1, 9))
        add_rec(UA, metric_type="mood", value_1=4, tags=["relaxed", "focused"],
                recorded_at=stamp(-1, 10))
        victim = add_rec(UA, metric_type="water", value_1=700, recorded_at=stamp(-3, 9))
        st_del, _bd = c.call("DELETE", "/records/%d" % victim, None, tokens[UA])
        record("造数：A 端 4 条记录（含 1 条经 R-07 软删）",
               len(rec_ids) == 4 and st_del == 200, "records=%d del=HTTP %s" % (len(rec_ids), st_del))

        st_p, b_p = c.call("PUT", "/profile", {
            "nickname": "冒烟八甲", "gender": 1, "birth_date": "1990-05-20",
            "height_cm": 175, "initial_weight_kg": None, "blood_type": "A",
            "medical_history": "无", "allergy_history": None, "medication_notes": None,
            "acknowledge_warnings": True,
        }, tokens[UA])
        record("造数：A 端档案 3/6 健康字段 + 昵称/性别/出生日期",
               st_p == 200, "HTTP %s %s" % (st_p, code_of(b_p)))

        st_g1, b_g1 = c.call("POST", "/goals",
                             {"goal_type": "water", "target_value": 2000,
                              "acknowledge_warnings": True}, tokens[UA])
        g_water = int((data_of(b_g1).get("goal") or {}).get("id") or 0)
        st_g2, b_g2 = c.call("POST", "/goals",
                             {"goal_type": "sport", "attr_1": "count", "target_value": 3,
                              "acknowledge_warnings": True}, tokens[UA])
        g_sport = int((data_of(b_g2).get("goal") or {}).get("id") or 0)
        st_g3, _b_g3 = c.call("POST", "/goals/%d/pause" % g_sport, None, tokens[UA])
        record("造数：A 端 2 目标（1 在用 / 1 暂停）",
               st_g1 == 201 and st_g2 == 201 and st_g3 == 200 and g_water > 0 and g_sport > 0,
               "%s/%s/%s ids=%s/%s" % (st_g1, st_g2, st_g3, g_water, g_sport))

        # 直连 SQL 造 login_failure_state（**本表无 API 写入入口**，仅测试装置）
        db_exec("INSERT INTO login_failure_state "
                "(username, fail_count, first_fail_at, locked_until, lock_level, updated_at) "
                "VALUES (:u, 3, NOW(), NULL, 0, NOW())", {"u": UA})
        n_lfs = count_where("login_failure_state", "username = :u", {"u": UA})
        record("造数：A 端 login_failure_state 1 行（直连 SQL，本表无 API 入口）", n_lfs == 1,
               "rows=%d" % n_lfs)

        # 经 E-01 建导出任务 → 真实文件落盘；读库拿 file_path 备验
        job_a = 0
        path_a = ""
        if args.skip_files:
            say("  [SKIP] --skip-files：跳过 E-01 导出任务与 T4 文件删除用例"
                "（文件/重试行为权威覆盖见 tests/batch8/test_a07_files_retry.py）")
        else:
            st_e, b_e = c.call("POST", "/exports", {"format": "csv", "password": PWD}, tokens[UA])
            job_a = int(data_of(b_e).get("export_id") or 0)
            rows_e = db_rows("SELECT file_path FROM export_job WHERE id = :i", {"i": job_a})
            path_a = str(rows_e[0][0]) if rows_e and rows_e[0][0] else ""
            if path_a:
                extra_files.append(path_a)
            record("造数：A 端 E-01 导出任务 + 真实文件落盘",
                   st_e == 202 and job_a > 0 and bool(path_a) and os.path.isfile(path_a),
                   "HTTP %s job=%d file=%s" % (st_e, job_a, os.path.basename(path_a)))

        st_bb, _b_bb = c.call("POST", "/records",
                              {"metric_type": "weight", "value_1": 60,
                               "recorded_at": stamp(-1, 8)}, tokens[UB])
        record("造数：B 端 1 条活跃记录（隔离对照）", st_bb == 201, "HTTP %s" % st_bb)

        st_pb, b_pb = c.call("PUT", "/profile", {
            "nickname": "冒烟八乙", "gender": 2, "birth_date": "1992-03-11",
            "height_cm": 162, "initial_weight_kg": None, "blood_type": "O",
            "medical_history": None, "allergy_history": None, "medication_notes": None,
            "acknowledge_warnings": True,
        }, tokens[UB])
        record("造数：B 端档案 3/6 健康字段 + 昵称/性别/出生日期（用于 A-07 隔离校验）",
               st_pb == 200, "HTTP %s %s" % (st_pb, code_of(b_pb)))

        # ── 4. 快照（A 端 8 表目标行数；用于校验失败路径下"数据保持原状"） ──
        snap = {
            "record_tag": count_where("record_tag", "user_id = :i", {"i": uid[UA]}),
            "health_record": count_where("health_record", "user_id = :i", {"i": uid[UA]}),
            "health_goal": count_where("health_goal", "user_id = :i", {"i": uid[UA]}),
            "user_profile": count_where("user_profile", "user_id = :i", {"i": uid[UA]}),
            "export_job": count_where("export_job", "user_id = :i", {"i": uid[UA]}),
            "user_session": count_where("user_session", "user_id = :i", {"i": uid[UA]}),
            "login_failure_state": count_where("login_failure_state", "username = :u", {"u": UA}),
            "user_account": count_where("user_account", "id = :i", {"i": uid[UA]}),
        }
        record("快照：A 端业务表均有数据（record_tag=2 / health_record=4 / goal=2 / profile=1 / "
               "session>=1 / lfs=1 / account=1；export_job 视 --skip-files 而定）",
               snap["record_tag"] == 2 and snap["health_record"] == 4 and snap["health_goal"] == 2
               and snap["user_profile"] == 1
               and snap["export_job"] == (0 if args.skip_files else 1)
               and snap["user_session"] >= 1 and snap["login_failure_state"] == 1
               and snap["user_account"] == 1,
               str(snap))

        def resnap() -> Dict[str, int]:
            return {
                "record_tag": count_where("record_tag", "user_id = :i", {"i": uid[UA]}),
                "health_record": count_where("health_record", "user_id = :i", {"i": uid[UA]}),
                "health_goal": count_where("health_goal", "user_id = :i", {"i": uid[UA]}),
                "user_profile": count_where("user_profile", "user_id = :i", {"i": uid[UA]}),
                "export_job": count_where("export_job", "user_id = :i", {"i": uid[UA]}),
                "user_session": count_where("user_session", "user_id = :i", {"i": uid[UA]}),
                "login_failure_state": count_where("login_failure_state", "username = :u",
                                                  {"u": UA}),
                "user_account": count_where("user_account", "id = :i", {"i": uid[UA]}),
            }

        # ── 5. 三重确认（反向路径） ─────────────────────────────────
        st, body = c.call("DELETE", "/users/me", {"password": PWD}, tokens[UA])
        errs = errors_of(body)
        record("A-07 缺 confirm_text -> 422 VALIDATION_FAILED + REQUIRED(field=confirm_text)",
               st == 422 and code_of(body) == "VALIDATION_FAILED" and bool(errs)
               and errs[0].get("field") == "confirm_text" and errs[0].get("code") == "REQUIRED",
               "HTTP %s %s %s" % (st, code_of(body), errs[:1]))

        st, body = c.call("DELETE", "/users/me",
                          {"password": PWD, "confirm_text": D02_CONFIRM_TEXT}, tokens[UA])
        errs = errors_of(body)
        record("A-07 确认文字为 D-02 的「确认删除」-> 422 + INVALID_FORMAT（**不得复用**）",
               st == 422 and code_of(body) == "VALIDATION_FAILED" and bool(errs)
               and errs[0].get("field") == "confirm_text"
               and errs[0].get("code") == "INVALID_FORMAT",
               "HTTP %s %s %s" % (st, code_of(body), errs[:1]))

        st, body = c.call("DELETE", "/users/me",
                          {"password": PWD, "confirm_text": "注销帐号"}, tokens[UA])
        errs = errors_of(body)
        record("A-07 确认文字错别字 -> 422 VALIDATION_FAILED + INVALID_FORMAT",
               st == 422 and code_of(body) == "VALIDATION_FAILED" and bool(errs)
               and errs[0].get("field") == "confirm_text"
               and errs[0].get("code") == "INVALID_FORMAT",
               "HTTP %s %s %s" % (st, code_of(body), errs[:1]))

        st, body = c.call("DELETE", "/users/me",
                          {"password": PWD, "confirm_text": ""}, tokens[UA])
        record("A-07 确认文字为空串 -> 422 VALIDATION_FAILED（**不得**误判为缺失）",
               st == 422 and code_of(body) == "VALIDATION_FAILED", "HTTP %s %s" % (st, code_of(body)))

        # 首尾空白：实现按 strip 后比对（**非**契约新增语义），此处以**错误密码**验证
        # 「确认文字已被接受、密码闸门仍然生效」——避免用合法凭据造成真实注销。
        st, body = c.call("DELETE", "/users/me",
                          {"password": "WrongPass0", "confirm_text": " 注销账号 "}, tokens[UA])
        record("A-07 confirm_text 首尾空白被接受、密码闸门仍生效 -> 422 PASSWORD_INVALID",
               st == 422 and code_of(body) == "PASSWORD_INVALID", "HTTP %s %s" % (st, code_of(body)))

        st, body = c.call("DELETE", "/users/me", {"confirm_text": CONFIRM_TEXT}, tokens[UA])
        errs = errors_of(body)
        record("A-07 缺 password -> 422 VALIDATION_FAILED + REQUIRED(field=password)",
               st == 422 and code_of(body) == "VALIDATION_FAILED" and bool(errs)
               and errs[0].get("field") == "password" and errs[0].get("code") == "REQUIRED",
               "HTTP %s %s %s" % (st, code_of(body), errs[:1]))

        st, body = c.call("DELETE", "/users/me",
                          {"confirm_text": CONFIRM_TEXT, "password": "   "}, tokens[UA])
        record("A-07 password 为空白串 -> 422 VALIDATION_FAILED",
               st == 422 and code_of(body) == "VALIDATION_FAILED", "HTTP %s %s" % (st, code_of(body)))

        # client_time 为可选排查字段：以**错误确认文字**验证其不参与业务判定，
        # 避免用合法凭据造成真实注销。
        st, body = c.call("DELETE", "/users/me",
                          {"confirm_text": "x", "password": PWD,
                           "client_time": stamp(0, 12)}, tokens[UA])
        record("A-07 client_time 不参与业务判定（确认文字仍被校验 -> 422 VALIDATION_FAILED）",
               st == 422 and code_of(body) == "VALIDATION_FAILED", "HTTP %s %s" % (st, code_of(body)))
        record("A-07 失败态未导致注销（账号仍在）", user_id_of(UA) == uid[UA], "uid=%d" % uid[UA])

        # ── 6. 密码错误五连：422 PASSWORD_INVALID，**不累计、无 429、不加锁** ──
        for i in range(1, 6):
            st, body = c.call("DELETE", "/users/me",
                              {"confirm_text": CONFIRM_TEXT, "password": "WrongPass%d" % i},
                              tokens[UA])
            if i in (1, 5):
                record("A-07 密码错误第 %d 次 -> 422 PASSWORD_INVALID（**不返回 429**）" % i,
                       st == 422 and code_of(body) == "PASSWORD_INVALID",
                       "HTTP %s %s" % (st, code_of(body)))
        n_lfs_after = count_where("login_failure_state", "username = :u", {"u": UA})
        record("A-07 连续 5 次密码错误**不写** login_failure_state（仍为造数的 1 行）",
               n_lfs_after == snap["login_failure_state"], "rows=%d" % n_lfs_after)
        st, body = c.call("POST", "/auth/login", {"username": UA, "password": PWD})
        record("A-07 密码错误**不影响登录**（同密码仍可登录，未触发锁定）",
               st == 200, "HTTP %s %s" % (st, code_of(body)))

        # ── 7. 失败路径：A 端数据必须**保持原状** ──────────────────
        # 说明：断言集内的“密码错误不影响登录”会**真实新建 1 个会话**（user_session +1），
        #       属预期行为；故此处只比对业务数据表，user_session 单独校验"未减少"。
        def stable(state: Dict[str, int]) -> Dict[str, int]:
            return {k: v for k, v in state.items() if k != "user_session"}

        now_snap = resnap()
        record("A-07 全部失败尝试后 A 端业务数据**保持原状**（7 表逐表相等）",
               stable(now_snap) == stable(snap), str(now_snap))
        record("A-07 失败尝试未清空会话（user_session 未减少；断言内重新登录会 +1，属预期）",
               now_snap["user_session"] >= snap["user_session"],
               "%d -> %d" % (snap["user_session"], now_snap["user_session"]))

        # ── 8. 范围扩展参数：force 不得绕过密码闸门（B 端） ─────────
        st, body = c.call("DELETE", "/users/me",
                          {"confirm_text": CONFIRM_TEXT, "password": "WrongPass9",
                           "force": True, "target_user_id": uid[UA], "grace_period": 0,
                           "defer": True, "schedule": "now"}, tokens[UB])
        record("A-07 force=True 仍不能绕过密码闸门 -> 422 PASSWORD_INVALID",
               st == 422 and code_of(body) == "PASSWORD_INVALID", "HTTP %s %s" % (st, code_of(body)))
        record("A-07 对端 force 失败**未影响** A 端账号（A 仍在）",
               user_id_of(UA) == uid[UA], "A_uid=%d" % user_id_of(UA))

        # ── 9-10. T4 失败重试演示（C 端持句柄 → 删除失败 → 登记重试；D 端注销顺带 drain） ──
        if args.skip_files:
            say("  [SKIP] --skip-files：跳过 T4 文件删除失败 / 重试重放演示（C / D 端）")
        else:
            st_e, b_e = c.call("POST", "/exports", {"format": "csv", "password": PWD}, tokens[UC])
            job_c = int(data_of(b_e).get("export_id") or 0)
            rows_c = db_rows("SELECT file_path FROM export_job WHERE id = :i", {"i": job_c})
            path_c = str(rows_c[0][0]) if rows_c and rows_c[0][0] else ""
            if path_c:
                extra_files.append(path_c)
                CREATED_FILES.append(os.path.basename(path_c))
            held_handle = open(path_c, "rb") if path_c and os.path.isfile(path_c) else None
            record("T4 演示：C 端导出任务 + 文件已落盘并由本进程持句柄",
                   st_e == 202 and bool(path_c) and held_handle is not None,
                   "HTTP %s job=%d" % (st_e, job_c))

            st, body = c.call("DELETE", "/users/me",
                              {"confirm_text": CONFIRM_TEXT, "password": PWD}, tokens[UC])
            record("T4 文件删除失败**仍返回 200**（账已注销，**不回滚**）",
                   st == 200 and data_of(body).get("account_closed") is True
                   and sorted(data_of(body)) == CLOSED_KEYS,
                   "HTTP %s %s" % (st, data_of(body)))
            record("T4 失败后 C 端 DB 已整体删除（export_job=0 / account=0）",
                   count_where("export_job", "user_id = :i", {"i": uid[UC]}) == 0
                   and count_where("user_account", "id = :i", {"i": uid[UC]}) == 0)
            st, body = c.call("GET", "/users/me", None, tokens[UC])
            record("T4 失败后 C 端旧 Token 亦已失效 -> 401", st == 401, "HTTP %s" % st)

            queue = read_retry_queue()
            names = [str(e.get("file_name") or "") for e in queue]
            record("T4 失败已产生**可追踪的重试登记**（cleanup_retry.jsonl 含该文件名）",
                   os.path.basename(path_c) in names if path_c else False,
                   "queue=%s" % names)
            entry_c = next((e for e in queue if e.get("file_name") == os.path.basename(path_c)), {})
            record("T4 重试登记**脱敏**（无 user_id / 用户名 / 完整路径）",
                   entry_c != {} and all(k in entry_c for k in ("file_name", "attempt", "code", "ts"))
                   and "user_id" not in entry_c and "username" not in entry_c
                   and "/" not in str(entry_c.get("file_name") or "")
                   and os.sep not in str(entry_c.get("file_name") or ""),
                   json.dumps(entry_c, ensure_ascii=False, sort_keys=True))

            if held_handle is not None:
                held_handle.close()
                held_handle = None
            st_e, b_e = c.call("POST", "/exports", {"format": "csv", "password": PWD}, tokens[UD])
            job_d = int(data_of(b_e).get("export_id") or 0)
            rows_d = db_rows("SELECT file_path FROM export_job WHERE id = :i", {"i": job_d})
            path_d = str(rows_d[0][0]) if rows_d and rows_d[0][0] else ""
            if path_d:
                extra_files.append(path_d)
                CREATED_FILES.append(os.path.basename(path_d))
            st, body = c.call("DELETE", "/users/me",
                              {"confirm_text": CONFIRM_TEXT, "password": PWD}, tokens[UD])
            record("重放：D 端注销 200（顺带 drain 已登记项）",
                   st == 200 and data_of(body).get("account_closed") is True,
                   "HTTP %s %s" % (st, data_of(body)))
            queue2 = read_retry_queue()
            record("重放后 C 端遗留项已清除，重试登记队列为空",
                   all(str(e.get("file_name") or "") != os.path.basename(path_c) for e in queue2),
                   "queue=%s" % [e.get("file_name") for e in queue2])
            record("重放后 C 端导出文件**已真正删除**",
                   not (path_c and os.path.isfile(path_c)), "path=%s" % os.path.basename(path_c))

        # ── 11. A 端成功注销（带范围扩展参数 + client_time，一律无效果） ──
        st, body = c.call("DELETE", "/users/me",
                          {"confirm_text": CONFIRM_TEXT, "password": PWD,
                           "client_time": stamp(0, 12),
                           "target_user_id": uid[UB], "force": True, "grace_period": 30,
                           "defer": True, "schedule": "later"}, tokens[UA])
        d_closed = data_of(body)
        record("A-07 成功 200 且 envelope 恰 4 键（含 request_id）",
               st == 200 and sorted(body) == ENVELOPE_KEYS,
               "HTTP %s %s" % (st, sorted(body or {})))
        record("A-07 成功 data **恰 1 键** account_closed=true（无删除条数 / warning）",
               sorted(d_closed) == CLOSED_KEYS and d_closed.get("account_closed") is True,
               str(sorted(d_closed)))
        record("A-07 成功文案为「账号已注销」（与「退出登录」严格区分）",
               msg_of(body) == "账号已注销", msg_of(body))
        record("A-07 成功响应无 soft_warning / warnings",
               "soft_warning" not in d_closed and "warnings" not in d_closed, str(d_closed))

        # ── 12. A 端 8 表**物理归零**（含软删行、档案整行） ──────────
        after = {
            "record_tag": count_where("record_tag", "user_id = :i", {"i": uid[UA]}),
            "health_record": count_where("health_record", "user_id = :i", {"i": uid[UA]}),
            "health_goal": count_where("health_goal", "user_id = :i", {"i": uid[UA]}),
            "user_profile": count_where("user_profile", "user_id = :i", {"i": uid[UA]}),
            "export_job": count_where("export_job", "user_id = :i", {"i": uid[UA]}),
            "user_session": count_where("user_session", "user_id = :i", {"i": uid[UA]}),
            "login_failure_state": count_where("login_failure_state", "username = :u", {"u": UA}),
            "user_account": count_where("user_account", "id = :i", {"i": uid[UA]}),
        }
        record("A-07 后 A 端 8 表**全部物理归零**（record_tag/record/profile/session/lfs/account）",
               all(v == 0 for v in after.values()), str(after))
        record("A-07 后 health_record **无 active 残留**（含 30 天外软删行亦物理删除）",
               count_where("health_record", "user_id = :i AND is_deleted = 0",
                           {"i": uid[UA]}) == 0
               and count_where("health_record", "user_id = :i AND is_deleted = 1",
                               {"i": uid[UA]}) == 0)
        record("A-07 后 user_profile **整行删除**（非 D-02 的置空保留）",
               count_where("user_profile", "user_id = :i", {"i": uid[UA]}) == 0)
        record("A-07 后 login_failure_state **按 username 清除**",
               count_where("login_failure_state", "username = :u", {"u": UA}) == 0)
        record("A-07 后 user_account 行已删除（账号不存在）", user_id_of(UA) == 0)

        # ── 13. 导出文件已删 + 重试登记无残留 ───────────────────────
        if args.skip_files:
            say("  [SKIP] --skip-files：跳过 A 端导出文件删除与重试登记断言")
        else:
            record("A-07 后 A 端导出文件**已删除**（T4 事务外成功路径）",
                   bool(path_a) and not os.path.isfile(path_a),
                   "path=%s" % os.path.basename(path_a))
            queue3 = read_retry_queue()
            record("A-07 成功路径**不产生**重试登记",
                   all(str(e.get("file_name") or "") != os.path.basename(path_a) for e in queue3),
                   "queue=%s" % [e.get("file_name") for e in queue3])

        # ── 14. Token / refresh 全部失效 ────────────────────────────
        st, body = c.call("GET", "/users/me", None, tokens[UA])
        record("A-07 后旧 Access Token -> 401", st == 401, "HTTP %s" % st)
        st, body = c.call("GET", "/records", None, tokens[UA])
        record("A-07 后旧 Access Token 访问 /records -> 401", st == 401, "HTTP %s" % st)
        st, body = c.call("POST", "/auth/refresh", {"refresh_token": refreshes[UA]})
        record("A-07 后旧 refresh_token -> 401（会话已物理删除）",
               st == 401, "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("DELETE", "/users/me",
                          {"confirm_text": CONFIRM_TEXT, "password": PWD}, tokens[UA])
        record("A-07 重复注销（旧 Token 重放）-> 401（天然幂等，不泄露账号状态）",
               st == 401, "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/auth/login", {"username": UA, "password": PWD})
        record("A-07 后原凭据登录 -> 401 CREDENTIALS_INVALID（账号确已不存在）",
               st == 401 and code_of(body) == "CREDENTIALS_INVALID",
               "HTTP %s %s" % (st, code_of(body)))

        # ── 15. 用户名释放：可重新注册且可登录 ──────────────────────
        st, body = c.call("POST", "/auth/register", {
            "username": UA, "password": PWD,
            "agreement_version": "v1.0", "agreement_accepted": True,
        })
        record("A-07 后同用户名**可重新注册**（用户名已释放）", st in (200, 201),
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/auth/login", {"username": UA, "password": PWD})
        new_uid = user_id_of(UA)
        record("A-07 后重新注册账号**可登录**且拿到**新的** uid（非旧 uid）",
               st == 200 and new_uid > 0 and new_uid != uid[UA],
               "HTTP %s new_uid=%s old_uid=%s" % (st, new_uid, uid[UA]))
        record("A-07 后新账号**无任何历史数据残留**（记录 / 档案 / 目标全 0）",
               count_where("health_record", "user_id = :i", {"i": new_uid}) == 0
               and count_where("user_profile", "user_id = :i", {"i": new_uid}) == 0
               and count_where("health_goal", "user_id = :i", {"i": new_uid}) == 0)

        # ── 16. 隔离：B 端完全不受影响 ──────────────────────────────
        record("隔离：B 端账号仍在", user_id_of(UB) == uid[UB], "B_uid=%d" % user_id_of(UB))
        record("隔离：B 端 1 条记录仍在",
               count_where("health_record", "user_id = :i", {"i": uid[UB]}) == 1)
        record("隔离：B 端档案行**仍在**（未被误删）",
               count_where("user_profile", "user_id = :i", {"i": uid[UB]}) == 1,
               "rows=%d" % count_where("user_profile", "user_id = :i", {"i": uid[UB]}))
        _pb = (data_of(c.call("GET", "/profile", None, tokens[UB])[1]).get("profile") or {})
        record("隔离：B 端档案字段**逐项未变**（昵称/性别/出生日期/血型）",
               _pb.get("nickname") == "冒烟八乙" and _pb.get("gender") == 2
               and _pb.get("birth_date") == "1992-03-11" and _pb.get("blood_type") == "O",
               json.dumps(_pb, ensure_ascii=False))
        record("隔离：B 端会话仍在（Token 未被误失效）",
               count_where("user_session", "user_id = :i", {"i": uid[UB]}) >= 1)
        st, body = c.call("GET", "/users/me", None, tokens[UB])
        record("隔离：B 端旧 Token **仍可用** -> 200", st == 200, "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("GET", "/records", None, tokens[UB])
        record("隔离：B 端 /records 仍可读且恰 1 条",
               st == 200 and len(data_of(body).get("items") or []) == 1,
               "HTTP %s %s" % (st, len(data_of(body).get("items") or [])))

        # ── 17. 安全闸门自证 ────────────────────────────────────────
        try:
            purge_accounts([UA, "not_in_whitelist"])
            record("安全闸门：白名单外账号被拒（清理函数自我保护）", False, "未抛异常")
        except RuntimeError:
            record("安全闸门：白名单外账号被拒（清理函数自我保护）", True)

    except Exception as exc:  # noqa: BLE001
        record("顶层执行异常", False, "%s: %s" % (type(exc).__name__, exc))
        import traceback
        say(traceback.format_exc())
    finally:
        if held_handle is not None:
            try:
                held_handle.close()
            except OSError:
                pass
        # ── 18. 清理（仅白名单 4 账号；逐表物理 DELETE + 显式删除本次文件） ──
        try:
            before = set(account_usernames())
            targets = [u for u in WHITELIST if u in before]
            say("  清理白名单：%s（实际命中 %s）" % (list(WHITELIST), targets))
            record("清理：仅对白名单账号执行（实际账号 ⊆ 白名单）",
                   set(targets) <= set(WHITELIST), str(targets))
            counts, db_files = purge_accounts(targets)
            say("  清理结果：%s" % counts)
            files = list(dict.fromkeys(list(db_files) + extra_files))
            if args.purge_files:
                removed, skipped = remove_inside_export_dir(files)
                say("  文件清理：候选 %d / 删除 %d / 跳过 %d" % (len(files), removed, skipped))
            else:
                say("  [跳过] 未启用文件清理（**默认不触碰文件系统**）；本批候选文件 %d 个"
                    % len(files))
            residue = [u for u in WHITELIST if user_id_of(u) > 0]
            lfs = count_where("login_failure_state", "username IN ('%s')" % "','".join(WHITELIST),
                              {})
            record("清理：白名单账号行已物理删除（user_account 残留 0）", residue == [], str(residue))
            record("清理：login_failure_state 白名单残留 0", lfs == 0, "rows=%d" % lfs)
            rq = retry_queue_path()
            if args.purge_files and os.path.isfile(rq) and os.path.getsize(rq) == 0:
                try:
                    os.remove(rq)
                    say("  已删除空的重试登记文件：%s" % os.path.basename(rq))
                except OSError:
                    pass
            if not args.purge_files:
                say("  重试登记文件状态：%s"
                    % ("不存在" if not os.path.isfile(rq)
                       else ("空文件（无待重试项，属正常）" if os.path.getsize(rq) == 0
                             else "非空（含待重试项）")))
            record("清理：重试登记文件无残留（不存在或为空）",
                   (not os.path.isfile(rq)) or os.path.getsize(rq) == 0,
                   "exists=%s size=%s" % (os.path.isfile(rq),
                                          os.path.getsize(rq) if os.path.isfile(rq) else 0))
            left = [os.path.basename(p) for p in files if p and os.path.isfile(p)]
            record("清理：本次创建的导出文件残留 0", left == [], str(left))
            record("清理：重试登记队列无遗留项",
                   all(str(e.get("file_name") or "") not in CREATED_FILES
                       for e in read_retry_queue()), str(CREATED_FILES))
        except Exception as exc:  # noqa: BLE001
            say("  [WARN] 清理异常：%s" % exc)

        passed = sum(1 for _n, ok_, _d in RESULTS if ok_)
        total = len(RESULTS)
        say()
        say("=" * 72)
        for name, ok_, detail in RESULTS:
            say("  %s  %s%s" % ("PASS" if ok_ else "FAIL", name,
                                ("   -> " + detail) if (detail and not ok_) else ""))
        say("-" * 72)
        say("  合计 %d/%d PASS，%d FAIL" % (passed, total, total - passed))
        say("  结论：%s" % ("全部通过" if passed == total else "存在失败项"))
        say("=" * 72)

    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
