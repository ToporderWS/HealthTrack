# -*- coding: utf-8 -*-
"""S2 第七批 D-01～D-02（数据总览 / 清空全部数据）真实 HTTP 联调冒烟（双账号 · 造数 · 断言 · 清理）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch7_http_smoke.py
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch7_http_smoke.py --port 5000

前置：后端已启动（``cd backend && .venv/Scripts/python.exe wsgi.py``）。

口径：
1. 注册 / 登录 ``tstb7smokea``（本端）/ ``tstb7smokeb``（对端）；两账号均以 ``tst`` 前缀命名，
   与本批 ``tests/batch7/conftest.py`` 的清理范围一致（``tst%``）。
2. **D-02 是破坏性操作**：仅对本脚本自建的 ``tstb7smoke*`` 两个账号执行清空；
   **绝不对任何非测试账号执行**。
3. 本端造数：经 **R-01 真实 HTTP** 写入 3 条活跃记录（weight / water / mood+tags）、
   1 条 water 后经 **R-07 软删**（验证软删不计入 D-01）；经 **P-02** 设档案 3/6 健康字段
   （昵称 / 性别 / 出生日期同设，用于验证保留）；经 **G-02/G-04** 建 1 在用 + 1 暂停目标。
4. 对端造数：1 条活跃记录（验证 ``user_id`` 隔离）。
5. 断言 D-01（4 键 / 固定顺序 / 只含有数据 / 软删排除 / goals / profile）与
   D-02（三重确认 / 密码错 422 且无 429 / 4 类范围 / 软删 + ``deleted_marker`` /
   档案仅置空 6 字段 / 账号会话导出任务登录失败全保留 / 二次执行全 0 / 越权隔离）。
6. 收尾：``finally`` 清理本次测试数据（**仅 ``tstb7smoke*`` 两个账号**，逐表物理 DELETE）。
   白名单判定为「**实际账号 ⊆ 白名单**」，不做批量删除绕过安全确认。

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
from typing import Any, Dict, List, Optional, Tuple

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(PROJECT, "backend")

DEFAULT_PORT = 5000
PWD = "Kangji2026"
UA = "tstb7smokea"
UB = "tstb7smokeb"
#: 清理白名单（**唯一**允许被物理删除的账号集合）
WHITELIST = (UA, UB)

#: 8 类指标冻结顺序（C3）
METRIC_ORDER = ["weight", "bp", "heart", "glucose", "sleep", "water", "sport", "mood"]

#: D-01 顶层 4 键（冻结）
SUMMARY_KEYS = ["by_metric", "goals", "profile", "total_records"]
#: D-01 ``by_metric`` 每项 4 键（冻结）
METRIC_ITEM_KEYS = ["count", "first_recorded_at", "last_recorded_at", "metric_type"]
#: D-02 成功响应 6 键（冻结）
CLEAR_KEYS = ["account_kept", "deleted_goals", "deleted_records", "deleted_tags",
              "profile_health_fields_cleared", "scope"]
#: D-02 执行范围（逐字逐序冻结，C5）
CLEAR_SCOPE = ["health_records", "record_tags", "goals", "profile_health_fields"]
#: ``user_profile`` 6 个健康字段
PROFILE_HEALTH_FIELDS = ["height_cm", "initial_weight_kg", "blood_type",
                         "medical_history", "allergy_history", "medication_notes"]
#: 档案保留字段（D-02 后必须仍在）
PROFILE_KEEP_FIELDS = ["nickname", "gender", "birth_date"]

DT_FMT = "%Y-%m-%d %H:%M:%S"

RESULTS: List[Tuple[str, bool, str]] = []
FAILS: List[str] = []


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
    return (body or {}).get("data") or {}


def code_of(body: Any) -> str:
    return (body or {}).get("code") or ""


def msg_of(body: Any) -> str:
    return (body or {}).get("message") or ""


# ════════════════════════════════════════════════════════════════════
# 时间工具（本地墙上时间，与 D-4 一致）
# ════════════════════════════════════════════════════════════════════
def stamp(day_offset: int, hour: int = 9, minute: int = 0, second: int = 0) -> str:
    day = datetime.now().date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute, second)).strftime(DT_FMT)


def parse_dt(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.strptime(str(text), DT_FMT)
    except ValueError:
        return None


# ════════════════════════════════════════════════════════════════════
# DB（**仅**用于：D-02 后的库侧只读核查 + 收尾清理 tst 账号）
# ════════════════════════════════════════════════════════════════════
def engine():  # noqa: ANN201
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from sqlalchemy import create_engine

    from app.core.config import load_config

    return create_engine(load_config("development")["SQLALCHEMY_DATABASE_URI"])


def db_rows(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
    from sqlalchemy import text

    eng = engine()
    with eng.connect() as conn:
        return conn.execute(text(sql), params or {}).all()


def user_id_of(username: str) -> int:
    rows = db_rows("SELECT id FROM user_account WHERE username = :u", {"u": username})
    return int(rows[0][0]) if rows else 0


def account_usernames() -> List[str]:
    return [str(r[0]) for r in db_rows("SELECT username FROM user_account ORDER BY id")]


def purge_accounts(usernames: List[str]) -> Dict[str, int]:
    """逐表**物理 DELETE** 白名单账号的全部数据（单事务）。

    **安全闸门**：调用前先校验「实际传参 ⊆ 白名单」，否则直接拒绝执行。
    """
    from sqlalchemy import text

    outside = [u for u in usernames if u not in WHITELIST]
    if outside:
        raise RuntimeError("拒绝清理：账号 %s 不在白名单 %s 内" % (outside, list(WHITELIST)))

    eng = engine()
    counts: Dict[str, int] = {}
    # 说明：``login_failure_state`` **没有** ``user_id`` 列（主键为 ``username``），
    #       ``user_session`` 的失效标记是 ``revoked_at``（**没有** ``is_revoked``）。
    tables = ("record_tag", "health_record", "health_goal", "export_job",
              "user_session", "user_profile")
    with eng.begin() as conn:
        ids = [int(r[0]) for r in conn.execute(text(
            "SELECT id FROM user_account WHERE username IN (" +
            ",".join(":u%d" % i for i in range(len(usernames))) + ")"
        ), {"u%d" % i: n for i, n in enumerate(usernames)}).all()]
        if not ids:
            return counts
        holder = ",".join(":i%d" % i for i in range(len(ids)))
        params = {"i%d" % i: v for i, v in enumerate(ids)}
        for table in tables:
            res = conn.execute(text(
                "DELETE FROM %s WHERE user_id IN (%s)" % (table, holder)), params)
            counts[table] = int(res.rowcount or 0)
        res = conn.execute(text(
            "DELETE FROM login_failure_state WHERE username IN (" +
            ",".join(":u%d" % i for i in range(len(usernames))) + ")"
        ), {"u%d" % i: n for i, n in enumerate(usernames)})
        counts["login_failure_state"] = int(res.rowcount or 0)
        res = conn.execute(text(
            "DELETE FROM user_account WHERE id IN (%s)" % holder), params)
        counts["user_account"] = int(res.rowcount or 0)
    return counts


# ════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════
def main() -> int:  # noqa: C901
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    c = Client("http://%s:%d/api/v1" % (args.host, args.port))
    token_a: Optional[str] = None
    token_b: Optional[str] = None

    try:
        # ── 0. 连通性 ───────────────────────────────────────────────
        st, body = c.call("GET", "/health")
        if st != 200:
            say("[FATAL] 后端未就绪：GET /api/v1/health -> HTTP %s。"
                "请先启动：cd backend && .venv/Scripts/python.exe wsgi.py" % st)
            return 2
        record("冒烟：GET /api/v1/health 200 OK", code_of(body) == "OK", "HTTP %s" % st)

        # ── 1. 双账号 ───────────────────────────────────────────────
        def boot(user: str) -> str:
            c.call("POST", "/auth/register", {
                "username": user, "password": PWD,
                "agreement_version": "v1.0", "agreement_accepted": True,
            })
            st2, b2 = c.call("POST", "/auth/login", {"username": user, "password": PWD})
            if st2 != 200:
                raise RuntimeError("账号 %s 登录失败 HTTP %s %s" % (user, st2, code_of(b2)))
            return data_of(b2)["tokens"]["access_token"]

        token_a = boot(UA)
        token_b = boot(UB)
        record("双账号就绪（%s 本端 / %s 对端）" % (UA, UB), bool(token_a and token_b))

        # ── 2. 鉴权 ─────────────────────────────────────────────────
        st1, _ = c.call("GET", "/me/data/summary")
        st2, _ = c.call("POST", "/me/data/clear", {"confirm_text": "确认删除"})
        record("D-01 无 Token -> 401", st1 == 401, "HTTP %s" % st1)
        record("D-02 无 Token -> 401", st2 == 401, "HTTP %s" % st2)

        st, body = c.call("GET", "/me/data/summary?user_id=1", None, token_a)
        record("D-01 query 携带 user_id -> 400 INVALID_PARAM",
               st == 400 and code_of(body) == "INVALID_PARAM", "HTTP %s %s" % (st, code_of(body)))

        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD,
                           "acknowledge_irreversible": True, "user_id": 1}, token_a)
        record("D-02 body 携带 user_id -> 400 INVALID_PARAM",
               st == 400 and code_of(body) == "INVALID_PARAM", "HTTP %s %s" % (st, code_of(body)))

        # ── 3. 空数据 D-01（本端 / 对端） ────────────────────────────
        st, body = c.call("GET", "/me/data/summary", None, token_a)
        d0 = data_of(body)
        record("D-01 空数据 200 且 envelope 恰 4 键 + request_id",
               st == 200 and sorted(body) == ["code", "data", "message", "request_id"],
               "HTTP %s %s" % (st, sorted(body or {})))
        record("D-01 空数据 data 恰 4 键", sorted(d0) == SUMMARY_KEYS, str(sorted(d0)))
        record("D-01 空数据 total_records = 0", d0.get("total_records") == 0,
               str(d0.get("total_records")))
        record("D-01 空数据 by_metric = []（**不**逐类返回 0 行）",
               d0.get("by_metric") == [], str(d0.get("by_metric")))
        record("D-01 空数据 goals 全 0",
               d0.get("goals") == {"active_count": 0, "paused_count": 0}, str(d0.get("goals")))
        record("D-01 空数据 profile = 0/6",
               d0.get("profile") == {"health_fields_filled": 0, "health_fields_total": 6},
               str(d0.get("profile")))

        # ── 4. 本端造数（3 活跃 + 1 软删 + 档案 3/6 + 2 目标） ──────
        rec_ids: List[int] = []

        def add_rec(**payload: Any) -> int:
            st2, b2 = c.call("POST", "/records", payload, token_a)
            if st2 != 201:
                raise RuntimeError("R-01 写入失败 HTTP %s %s payload=%s"
                                   % (st2, code_of(b2), payload))
            rid = int(data_of(b2)["record"]["id"])
            rec_ids.append(rid)
            return rid

        t_w = stamp(-2, 9)
        t_h2o = stamp(-1, 9)
        t_mood = stamp(-1, 10)
        add_rec(metric_type="weight", value_1=70.50, recorded_at=t_w)
        add_rec(metric_type="water", value_1=500, recorded_at=t_h2o)
        add_rec(metric_type="mood", value_1=4, tags=["relaxed", "focused"], recorded_at=t_mood)
        victim = add_rec(metric_type="water", value_1=700, recorded_at=stamp(-3, 9))
        st_del, _bd = c.call("DELETE", "/records/%d" % victim, None, token_a)
        record("造数：本端写入 4 条 / 软删 1 条（HTTP 200）",
               len(rec_ids) == 4 and st_del == 200,
               "records=%d del=HTTP %s" % (len(rec_ids), st_del))

        st_p, b_p = c.call("PUT", "/profile", {
            "nickname": "冒烟甲", "gender": 1, "birth_date": "1990-05-20",
            "height_cm": 175, "initial_weight_kg": None, "blood_type": "A",
            "medical_history": "无", "allergy_history": None, "medication_notes": None,
            "acknowledge_warnings": True,
        }, token_a)
        record("造数：P-02 档案 3/6 健康字段 + 昵称/性别/出生日期", st_p == 200,
               "HTTP %s %s" % (st_p, code_of(b_p)))

        st_g1, b_g1 = c.call("POST", "/goals",
                             {"goal_type": "water", "target_value": 2000,
                              "acknowledge_warnings": True}, token_a)
        g_water = int((data_of(b_g1).get("goal") or {}).get("id") or 0)
        st_g2, b_g2 = c.call("POST", "/goals",
                             {"goal_type": "sport", "attr_1": "count", "target_value": 3,
                              "acknowledge_warnings": True}, token_a)
        g_sport = int((data_of(b_g2).get("goal") or {}).get("id") or 0)
        st_g3, b_g3 = c.call("POST", "/goals/%d/pause" % g_sport, None, token_a)
        record("造数：G-02 建 2 目标 + G-04 暂停 1 个",
               st_g1 == 201 and st_g2 == 201 and st_g3 == 200 and g_water > 0 and g_sport > 0,
               "%s/%s/%s ids=%s/%s" % (st_g1, st_g2, st_g3, g_water, g_sport))

        # ── 5. 对端造数（1 条活跃，验证隔离） ────────────────────────
        st_bb, b_bb = c.call("POST", "/records",
                             {"metric_type": "weight", "value_1": 60,
                              "recorded_at": stamp(-1, 8)}, token_b)
        record("造数：对端 1 条活跃记录", st_bb == 201, "HTTP %s" % st_bb)

        # ── 6. D-01 本端（固定顺序 / 只含有数据 / 软删排除） ─────────
        st, body = c.call("GET", "/me/data/summary", None, token_a)
        d1 = data_of(body)
        record("D-01 本端 200 且 data 恰 4 键", st == 200 and sorted(d1) == SUMMARY_KEYS,
               "HTTP %s %s" % (st, sorted(d1)))
        record("D-01 total_records = 3（软删 1 条不计入）", d1.get("total_records") == 3,
               str(d1.get("total_records")))
        items = d1.get("by_metric") or []
        record("D-01 by_metric 每项恰 4 键",
               bool(items) and all(sorted(it) == METRIC_ITEM_KEYS for it in items),
               str(sorted(items[0]) if items else "[]"))
        record("D-01 by_metric 按 METRIC_TYPES **固定顺序**且只含有数据（weight/water/mood）",
               [it["metric_type"] for it in items] == ["weight", "water", "mood"],
               str([it["metric_type"] for it in items]))
        record("D-01 by_metric count 各为 1（软删 water 不计入）",
               all(int(it["count"]) == 1 for it in items),
               str([it["count"] for it in items]))
        item_w = next((it for it in items if it["metric_type"] == "weight"), {})
        record("D-01 first/last recorded_at = 造数时间且格式冻结",
               parse_dt(item_w.get("first_recorded_at")) is not None
               and parse_dt(item_w.get("last_recorded_at")) is not None
               and item_w.get("first_recorded_at") == t_w
               and item_w.get("last_recorded_at") == t_w,
               str(item_w))
        record("D-01 goals = active 1 / paused 1（软删目标不计入）",
               d1.get("goals") == {"active_count": 1, "paused_count": 1}, str(d1.get("goals")))
        record("D-01 profile = 3/6（昵称/性别/出生日期不计入）",
               d1.get("profile") == {"health_fields_filled": 3, "health_fields_total": 6},
               str(d1.get("profile")))
        record("D-01 响应**无任何数值统计字段**",
               not any(k in json.dumps(d1) for k in
                       ("value_1", "value_2", "value_3", "avg", "sum", "max", "min", "unit")),
               "")

        d1_txt = json.dumps(d1, ensure_ascii=False, sort_keys=True)
        st, body = c.call("GET", "/me/data/summary", None, token_a)
        record("D-01 GET 幂等（两次响应一致）",
               json.dumps(data_of(body), ensure_ascii=False, sort_keys=True) == d1_txt)

        # ── 7. D-01 对端（隔离：只看到自己的 1 条） ──────────────────
        st, body = c.call("GET", "/me/data/summary", None, token_b)
        d_b = data_of(body)
        record("D-01 隔离：对端 total_records = 1（看不到本端 3 条）",
               d_b.get("total_records") == 1
               and [it["metric_type"] for it in d_b.get("by_metric") or []] == ["weight"],
               "%s %s" % (d_b.get("total_records"),
                          [it["metric_type"] for it in d_b.get("by_metric") or []]))
        record("D-01 隔离：对端 goals / profile 均为空",
               d_b.get("goals") == {"active_count": 0, "paused_count": 0}
               and d_b.get("profile") == {"health_fields_filled": 0, "health_fields_total": 6},
               "%s %s" % (d_b.get("goals"), d_b.get("profile")))

        # ── 8. D-02 三重确认反向（必须 422 且**数据不变**） ─────────
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认", "password": PWD,
                           "acknowledge_irreversible": True}, token_a)
        record("D-02 confirm_text 不为「确认删除」-> 422 VALIDATION_FAILED",
               st == 422 and code_of(body) == "VALIDATION_FAILED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/me/data/clear",
                          {"password": PWD, "acknowledge_irreversible": True}, token_a)
        record("D-02 缺 confirm_text -> 422", st == 422 and code_of(body) == "VALIDATION_FAILED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD}, token_a)
        record("D-02 缺 acknowledge_irreversible -> 422",
               st == 422 and code_of(body) == "VALIDATION_FAILED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD,
                           "acknowledge_irreversible": False}, token_a)
        record("D-02 acknowledge_irreversible=false -> 422",
               st == 422 and code_of(body) == "VALIDATION_FAILED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD,
                           "acknowledge_irreversible": "true"}, token_a)
        record("D-02 acknowledge_irreversible 字符串 \"true\" -> 422（必须布尔）",
               st == 422 and code_of(body) == "VALIDATION_FAILED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除",
                           "acknowledge_irreversible": True}, token_a)
        record("D-02 缺 password -> 422 VALIDATION_FAILED",
               st == 422 and code_of(body) == "VALIDATION_FAILED",
               "HTTP %s %s" % (st, code_of(body)))

        # ── 9. D-02 密码错误：422 PASSWORD_INVALID，**不累计失败、无 429** ─
        for i in range(1, 6):
            st, body = c.call("POST", "/me/data/clear",
                              {"confirm_text": "确认删除", "password": "WrongPass%d" % i,
                               "acknowledge_irreversible": True}, token_a)
            if i == 1 or i == 5:
                record("D-02 密码错误第 %d 次 -> 422 PASSWORD_INVALID（不返回 429）" % i,
                       st == 422 and code_of(body) == "PASSWORD_INVALID",
                       "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("GET", "/me/data/summary", None, token_a)
        record("D-02 连续 5 次密码错误后**数据未变**（total_records 仍 3）",
               data_of(body).get("total_records") == 3, str(data_of(body).get("total_records")))
        st, body = c.call("POST", "/auth/login", {"username": UA, "password": PWD})
        record("D-02 密码错误**不影响登录**（同密码仍可登录，未触发锁定）",
               st == 200, "HTTP %s %s" % (st, code_of(body)))
        if st == 200:
            token_a = data_of(body)["tokens"]["access_token"]

        # 库侧：错误密码不应写入 login_failure_state
        n_lfs = int(db_rows("SELECT COUNT(*) FROM login_failure_state WHERE username = :u",
                            {"u": UA})[0][0])
        record("DB：D-02 密码错误**不写** login_failure_state", n_lfs == 0, "rows=%d" % n_lfs)

        # ── 10. 清空前的库侧快照（用于 D-02 后比对保留项） ──────────
        uid_a = user_id_of(UA)
        n_sess_before = int(db_rows("SELECT COUNT(*) FROM user_session WHERE user_id = :i",
                                    {"i": uid_a})[0][0])
        n_job_before = int(db_rows("SELECT COUNT(*) FROM export_job WHERE user_id = :i",
                                   {"i": uid_a})[0][0])
        record("DB：清空前快照（本端 uid=%d，session=%d，export_job=%d）"
               % (uid_a, n_sess_before, n_job_before), uid_a > 0 and n_sess_before > 0)

        # ── 11. D-02 成功（三重确认齐全） ───────────────────────────
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD,
                           "acknowledge_irreversible": True}, token_a)
        dc = data_of(body)
        record("D-02 成功 200 且 envelope 恰 4 键 + request_id",
               st == 200 and sorted(body) == ["code", "data", "message", "request_id"],
               "HTTP %s %s" % (st, sorted(body or {})))
        record("D-02 data 恰 6 键（无 soft_warning / warnings）", sorted(dc) == CLEAR_KEYS,
               str(sorted(dc)))
        record("D-02 deleted_records = 3", dc.get("deleted_records") == 3,
               str(dc.get("deleted_records")))
        record("D-02 deleted_tags = 2（随主记录同步软删）", dc.get("deleted_tags") == 2,
               str(dc.get("deleted_tags")))
        record("D-02 deleted_goals = 2", dc.get("deleted_goals") == 2,
               str(dc.get("deleted_goals")))
        record("D-02 profile_health_fields_cleared = 3", dc.get("profile_health_fields_cleared") == 3,
               str(dc.get("profile_health_fields_cleared")))
        record("D-02 account_kept = True（账号保留）", dc.get("account_kept") is True,
               str(dc.get("account_kept")))
        record("D-02 scope **逐字逐序**冻结（C5）", dc.get("scope") == CLEAR_SCOPE,
               str(dc.get("scope")))
        record("D-02 成功文案冻结形态",
               msg_of(body) == "已清除 3 条记录。账号保留，数据已按规则清除", msg_of(body))

        # ── 12. 清空后 D-01 全归零 ──────────────────────────────────
        st, body = c.call("GET", "/me/data/summary", None, token_a)
        dz = data_of(body)
        record("D-02 后 D-01：total_records = 0 / by_metric = []",
               dz.get("total_records") == 0 and dz.get("by_metric") == [],
               "%s %s" % (dz.get("total_records"), dz.get("by_metric")))
        record("D-02 后 D-01：goals 全 0 / profile 0/6",
               dz.get("goals") == {"active_count": 0, "paused_count": 0}
               and dz.get("profile") == {"health_fields_filled": 0, "health_fields_total": 6},
               "%s %s" % (dz.get("goals"), dz.get("profile")))

        # ── 13. 库侧核查：软删语义与保留项 ──────────────────────────
        n_rec = int(db_rows("SELECT COUNT(*) FROM health_record WHERE user_id = :i",
                            {"i": uid_a})[0][0])
        n_rec_alive = int(db_rows(
            "SELECT COUNT(*) FROM health_record WHERE user_id = :i AND is_deleted = 0",
            {"i": uid_a})[0][0])
        n_rec_del = int(db_rows(
            "SELECT COUNT(*) FROM health_record WHERE user_id = :i AND is_deleted = 1 "
            "AND deleted_at IS NOT NULL", {"i": uid_a})[0][0])
        record("DB：health_record **物理行保留**（4 行）/ 活跃 0 / 软删 4",
               n_rec == 4 and n_rec_alive == 0 and n_rec_del == 4,
               "total=%d alive=%d deleted=%d" % (n_rec, n_rec_alive, n_rec_del))

        n_tag_alive = int(db_rows(
            "SELECT COUNT(*) FROM record_tag WHERE user_id = :i AND is_deleted = 0",
            {"i": uid_a})[0][0])
        n_tag_del = int(db_rows(
            "SELECT COUNT(*) FROM record_tag WHERE user_id = :i AND is_deleted = 1",
            {"i": uid_a})[0][0])
        record("DB：record_tag 全部软删（活跃 0 / 软删 2）",
               n_tag_alive == 0 and n_tag_del == 2, "alive=%d deleted=%d" % (n_tag_alive, n_tag_del))

        goal_rows = db_rows(
            "SELECT id, is_deleted, deleted_at, deleted_marker FROM health_goal "
            "WHERE user_id = :i ORDER BY id", {"i": uid_a})
        marker_ok = all(int(r[1]) == 1 and r[2] is not None and int(r[3]) == int(r[0])
                        for r in goal_rows)
        record("DB：health_goal 软删且 deleted_marker = id（释放唯一约束）",
               len(goal_rows) == 2 and marker_ok,
               str([(int(r[0]), int(r[1]), int(r[3])) for r in goal_rows]))

        prof = db_rows(
            "SELECT nickname, gender, birth_date, height_cm, initial_weight_kg, blood_type, "
            "medical_history, allergy_history, medication_notes FROM user_profile "
            "WHERE user_id = :i", {"i": uid_a})
        prof_ok = False
        if prof:
            p = prof[0]
            health_all_null = all(p[3 + k] is None for k in range(6))
            keep_ok = (p[0] == "冒烟甲" and int(p[1]) == 1 and str(p[2]) == "1990-05-20")
            prof_ok = health_all_null and keep_ok
        record("DB：user_profile **行保留** + 6 健康字段全 NULL + 昵称/性别/出生日期保留",
               prof_ok, str(prof[0]) if prof else "无档案行")

        n_acct = int(db_rows("SELECT COUNT(*) FROM user_account WHERE id = :i",
                             {"i": uid_a})[0][0])
        n_sess_after = int(db_rows("SELECT COUNT(*) FROM user_session WHERE user_id = :i",
                                   {"i": uid_a})[0][0])
        n_job_after = int(db_rows("SELECT COUNT(*) FROM export_job WHERE user_id = :i",
                                  {"i": uid_a})[0][0])
        n_lfs_after = int(db_rows("SELECT COUNT(*) FROM login_failure_state WHERE username = :u",
                                  {"u": UA})[0][0])
        record("DB：user_account 保留 / user_session 不变 / export_job 不变 / "
               "login_failure_state 不变",
               n_acct == 1 and n_sess_after == n_sess_before
               and n_job_after == n_job_before and n_lfs_after == 0,
               "acct=%d sess=%d->%d job=%d->%d lfs=%d"
               % (n_acct, n_sess_before, n_sess_after, n_job_before, n_job_after, n_lfs_after))

        st, body = c.call("GET", "/users/me", None, token_a)
        record("D-02 后原 Access Token **仍可用**（会话未被清）", st == 200,
               "HTTP %s %s" % (st, code_of(body)))

        # ── 14. 二次执行 → 全 0 ─────────────────────────────────────
        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD,
                           "acknowledge_irreversible": True}, token_a)
        d2 = data_of(body)
        record("D-02 二次执行 200 且四类计数全 0",
               st == 200 and d2.get("deleted_records") == 0 and d2.get("deleted_tags") == 0
               and d2.get("deleted_goals") == 0
               and d2.get("profile_health_fields_cleared") == 0,
               "HTTP %s %s" % (st, {k: d2.get(k) for k in
                                    ("deleted_records", "deleted_tags", "deleted_goals",
                                     "profile_health_fields_cleared")}))
        record("D-02 二次执行文案为「已清除 0 条记录。账号保留，数据已按规则清除」",
               msg_of(body) == "已清除 0 条记录。账号保留，数据已按规则清除", msg_of(body))

        # ── 15. 越权 / 范围扩展参数（对端） ─────────────────────────
        st, body = c.call("GET", "/me/data/summary", None, token_b)
        record("隔离：本端清空**不影响**对端（对端 total_records 仍 1）",
               data_of(body).get("total_records") == 1,
               str(data_of(body).get("total_records")))

        st, body = c.call("POST", "/me/data/clear",
                          {"confirm_text": "确认删除", "password": PWD,
                           "acknowledge_irreversible": True,
                           "include_profile_row": True, "delete_account": True,
                           "include_sessions": True, "force": True}, token_b)
        uid_b = user_id_of(UB)
        n_acct_b = int(db_rows("SELECT COUNT(*) FROM user_account WHERE id = :i",
                               {"i": uid_b})[0][0])
        n_prof_b = int(db_rows("SELECT COUNT(*) FROM user_profile WHERE user_id = :i",
                               {"i": uid_b})[0][0])
        record("D-02 范围扩展参数（include_profile_row/delete_account/…）**无任何效果**",
               st == 200 and data_of(body).get("deleted_records") == 1
               and data_of(body).get("account_kept") is True
               and n_acct_b == 1 and n_prof_b == 0,
               "HTTP %s acct=%d prof=%d" % (st, n_acct_b, n_prof_b))
        record("隔离：对端清空**不影响**本端（本端仍 0）",
               data_of(c.call("GET", "/me/data/summary", None, token_a)[1]).get("total_records") == 0)

        # 安全闸门自证：白名单外账号一律拒绝
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
        # ── 16. 清理（**仅** tstb7smoke* 两个账号；逐表白名单物理 DELETE） ──
        try:
            before = set(account_usernames())
            targets = [u for u in WHITELIST if u in before]
            say("  清理白名单：%s（实际命中 %s）" % (list(WHITELIST), targets))
            record("清理：仅对白名单账号执行（实际账号 ⊆ 白名单）",
                   set(targets) <= set(WHITELIST), str(targets))
            counts = purge_accounts(targets)
            say("  清理结果：%s" % counts)
            record("清理：测试账号数据已物理删除（user_account = 2）",
                   int(counts.get("user_account", 0)) == 2, str(counts))
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
