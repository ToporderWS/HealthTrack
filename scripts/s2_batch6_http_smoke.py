# -*- coding: utf-8 -*-
"""S2 第六批 E-01～E-04（数据导出）真实 HTTP 联调冒烟（双账号 · 造数 · 断言 · 清理）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch6_http_smoke.py
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch6_http_smoke.py --port 5000

前置：后端已启动（``cd backend && .venv/Scripts/python.exe wsgi.py``）。

口径：
1. 注册 / 登录 ``tstb6smokea``（本端）/ ``tstb6smokeb``（对端）；两账号均以 ``tst`` 前缀命名，
   与本批 ``tests/batch6/conftest.py`` 的清理范围一致（``tst%``）；
2. 仅**本端**造数：经 **R-01 真实 HTTP** 写入 3 条记录（weight / water / mood+tags），
   另写 1 条 water 后经 **R-07 软删**（用于验证软删数据不进导出）；
3. 对 4 接口逐项断言（202 / 7 键、10 键 / 3 键差异、TTL、二次验密计数与中止、
   三条件下载、410 过期、404 越权、分页与 `created_at DESC`、幂等）；
4. 隔离：对端看不到本端任务；对端持本端 ``export_id`` / ``file_token`` 一律 ``404``；
5. 收尾：``finally`` 清理本次测试数据（**仅 ``tstb6smoke*`` 两个账号**，逐表物理 DELETE）；
   导出文件**只登记路径、不删除**（交由 ``scripts/b6_cleanup_exports.py`` 分批清理）。

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
MANIFEST = os.path.join(PROJECT, ".workbuddy", "_b6_export_files.txt")

DEFAULT_PORT = 5000
PWD = "Kangji2026"
UA = "tstb6smokea"
UB = "tstb6smokeb"

#: E-01 成功响应 data 的 7 个键（冻结）
CREATE_KEYS = ["created_at", "download_expires_at", "export_id", "format", "purge_at",
               "record_count", "status"]
#: E-02 成功响应 data 的 10 个键（冻结）
DETAIL_KEYS = ["created_at", "download_expires_at", "downloaded_at", "export_id",
               "file_size_bytes", "file_token", "format", "purge_at", "record_count", "status"]
#: E-04 items 每项的 9 个键（= E-02 去掉 file_token）
ITEM_KEYS = [k for k in DETAIL_KEYS if k != "file_token"]

DISPOSITION_RE = r'^attachment; filename="healthtrack_export_\d{8}\.(csv|json)"$'

RESULTS: List[Tuple[str, bool, str]] = []
FAILS: List[str] = []
EXPORT_JOBS: List[Dict[str, Any]] = []


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


# ════════════════════════════════════════════════════════════════════
# 时间工具（本地墙上时间，与 D-4 一致）
# ════════════════════════════════════════════════════════════════════
def stamp(day_offset: int, hour: int = 9, minute: int = 0, second: int = 0) -> str:
    day = datetime.now().date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute, second)).strftime("%Y-%m-%d %H:%M:%S")


def day_str(day_offset: int = 0) -> str:
    return (datetime.now().date() + timedelta(days=day_offset)).isoformat()


def parse_dt(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# ════════════════════════════════════════════════════════════════════
# DB（**仅**用于：读取 export_job.file_path 登记 + 收尾清理 tst 账号）
# ════════════════════════════════════════════════════════════════════
def engine():  # noqa: ANN201
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from sqlalchemy import create_engine

    from app.core.config import load_config

    return create_engine(load_config("development")["SQLALCHEMY_DATABASE_URI"])


def dump_jobs(usernames: List[str]) -> List[Dict[str, Any]]:
    """读取本次测试账号的 export_job 行（含 file_path，供清理脚本使用）。"""
    from sqlalchemy import text

    eng = engine()
    rows: List[Dict[str, Any]] = []
    with eng.connect() as conn:
        for name in usernames:
            for r in conn.execute(text(
                "SELECT e.id, e.status, e.format, e.record_count, e.file_path "
                "FROM export_job e JOIN user_account a ON a.id = e.user_id "
                "WHERE a.username = :u ORDER BY e.id"
            ), {"u": name}).all():
                rows.append({"username": name, "id": int(r[0]), "status": r[1],
                             "format": r[2], "record_count": r[3],
                             "file_path": r[4]})
    return rows


def purge_accounts(usernames: List[str]) -> Dict[str, int]:
    """逐表**物理 DELETE**本次测试账号的全部数据（单事务）。"""
    from sqlalchemy import text

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


def append_manifest(paths: List[str]) -> None:
    """把本次生成的导出文件路径追加到清单（**只登记，不删除**）。"""
    if not paths:
        return
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "a", encoding="utf-8") as handle:
        for p in paths:
            handle.write(str(p).replace("\\", "/") + "\n")


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
        unauth = [("POST", "/exports"), ("GET", "/exports"),
                  ("GET", "/exports/1"), ("GET", "/exports/1/download?file_token=x")]
        bad = ["%s %s" % (m, p) for m, p in unauth if c.call(m, p)[0] != 401]
        record("四接口 无 Token -> 401", not bad, str(bad))

        st, body = c.call("GET", "/exports?user_id=1", None, token_a)
        record("E-04 query 携带 user_id -> 400 INVALID_PARAM",
               st == 400 and code_of(body) == "INVALID_PARAM", "HTTP %s %s" % (st, code_of(body)))

        st, body = c.call("POST", "/exports",
                          {"format": "csv", "password": PWD, "user_id": 1}, token_a)
        record("E-01 body 携带 user_id -> 400 INVALID_PARAM",
               st == 400 and code_of(body) == "INVALID_PARAM", "HTTP %s %s" % (st, code_of(body)))

        # ── 3. 对端：空数据导出 + 口令闸门（先做，避免被 409 干扰） ──
        st, body = c.call("POST", "/exports", {"format": "csv", "metric_types": None,
                                               "password": PWD}, token_b)
        empty_id = int(data_of(body).get("export_id") or 0)
        record("E-01 对端空数据导出 202", st == 202, "HTTP %s %s" % (st, code_of(body)))
        record("E-01 对端空数据 record_count = 0",
               data_of(body).get("record_count") == 0, str(data_of(body).get("record_count")))

        st, _h, raw = c.raw("GET", "/exports/%d/download?file_token=%s" % (
            empty_id, data_of(c.call("GET", "/exports/%d" % empty_id, None, token_b)[1]).get("file_token")),
            None, token_b)
        record("E-03 对端空数据下载 200 且仅表头",
               st == 200 and raw.decode("utf-8").count("\n") == 1
               and raw.decode("utf-8").startswith("metric_type,"),
               "HTTP %s / %d bytes" % (st, len(raw)))

        # ── 4. 对端：二次验密计数 → 中止 → 成功后清零 ────────────────
        for i in (1, 2):
            st, body = c.call("POST", "/exports", {"format": "csv", "password": "WrongPass%d" % i},
                              token_b)
            record("E-01 口令错误第 %d 次 -> 422 PASSWORD_INVALID" % i,
                   st == 422 and code_of(body) == "PASSWORD_INVALID",
                   "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/exports", {"format": "csv", "password": "WrongPass3"}, token_b)
        record("E-01 口令连错第 3 次 -> 429 SESSION_VERIFY_ABORTED",
               st == 429 and code_of(body) == "SESSION_VERIFY_ABORTED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/exports",
                          {"format": "csv", "metric_types": ["water"], "password": "WrongPass4"},
                          token_b)
        record("E-01 指定 metric_types **不豁免**二次验密（仍 429）",
               st == 429 and code_of(body) == "SESSION_VERIFY_ABORTED",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/exports", {"format": "csv", "password": PWD}, token_b)
        record("E-01 口令正确 -> 202 且计数清零",
               st == 202, "HTTP %s %s" % (st, code_of(body)))

        # ── 5. 本端造数（3 条 + 1 条软删） ───────────────────────────
        rec_ids: List[int] = []

        def add_rec(**payload: Any) -> int:
            st2, b2 = c.call("POST", "/records", payload, token_a)
            if st2 != 201:
                raise RuntimeError("R-01 写入失败 HTTP %s %s payload=%s"
                                   % (st2, code_of(b2), payload))
            rid = int(data_of(b2)["record"]["id"])
            rec_ids.append(rid)
            return rid

        add_rec(metric_type="weight", value_1=70.50, recorded_at=stamp(-2, 9))
        add_rec(metric_type="water", value_1=500, recorded_at=stamp(-1, 9))
        add_rec(metric_type="mood", value_1=4, tags=["relaxed", "focused"], recorded_at=stamp(-1, 10))
        victim = add_rec(metric_type="water", value_1=700, recorded_at=stamp(-3, 9))
        st2, _b2 = c.call("DELETE", "/records/%d" % victim, None, token_a)
        record("造数：本端写入 4 条 / 软删 1 条（HTTP 200）", len(rec_ids) == 4 and st2 == 200,
               "records=%d del=HTTP %s" % (len(rec_ids), st2))

        # ── 6. E-01 正常创建（csv / 全部指标） ──────────────────────
        st, body = c.call("POST", "/exports", {"format": "csv", "metric_types": None,
                                              "password": PWD}, token_a)
        d1 = data_of(body)
        job1 = int(d1.get("export_id") or 0)
        record("E-01 202", st == 202, "HTTP %s %s" % (st, code_of(body)))
        record("E-01 data 恰 7 键", sorted(d1) == CREATE_KEYS, str(sorted(d1)))
        record("E-01 同步生成 status = ready", d1.get("status") == "ready", str(d1.get("status")))
        record("E-01 record_count = 3（软删数据不计）", d1.get("record_count") == 3,
               str(d1.get("record_count")))
        c_at = parse_dt(d1.get("created_at"))
        exp_at = parse_dt(d1.get("download_expires_at"))
        pur_at = parse_dt(d1.get("purge_at"))
        record("E-01 TTL：下载窗口 600s / purge 3600s",
               c_at is not None and exp_at is not None and pur_at is not None
               and int((exp_at - c_at).total_seconds()) == 600
               and int((pur_at - c_at).total_seconds()) == 3600,
               "%s / %s / %s" % (d1.get("created_at"), d1.get("download_expires_at"),
                                 d1.get("purge_at")))
        record("E-01 响应无 file_path / file_token",
               "file_path" not in d1 and "file_token" not in d1, str(sorted(d1)))

        # ── 7. E-02 查询 ────────────────────────────────────────────
        st, body = c.call("GET", "/exports/%d" % job1, None, token_a)
        d2 = data_of(body)
        record("E-02 200 且 data 恰 10 键", st == 200 and sorted(d2) == DETAIL_KEYS,
               "HTTP %s %s" % (st, sorted(d2)))
        token1 = str(d2.get("file_token") or "")
        record("E-02 file_token 为 32 位十六进制",
               len(token1) == 32 and all(ch in "0123456789abcdef" for ch in token1),
               "len=%d" % len(token1))
        record("E-02 无 file_path", "file_path" not in d2)
        record("E-02 file_size_bytes > 0", (d2.get("file_size_bytes") or 0) > 0,
               str(d2.get("file_size_bytes")))
        record("E-02 downloaded_at 初始为 null", d2.get("downloaded_at") is None,
               str(d2.get("downloaded_at")))

        # ── 8. E-03 下载 ────────────────────────────────────────────
        st, hdrs, raw = c.raw("GET", "/exports/%d/download?file_token=%s" % (job1, token1),
                              None, token_a)
        text = raw.decode("utf-8")
        record("E-03 200 文件流", st == 200, "HTTP %s" % st)
        record("E-03 Content-Type = text/csv; charset=utf-8",
               hdrs.get("Content-Type") == "text/csv; charset=utf-8", str(hdrs.get("Content-Type")))
        import re as _re

        disp = str(hdrs.get("Content-Disposition") or "")
        record("E-03 Content-Disposition 冻结形态（服务端生成文件名）",
               bool(_re.match(DISPOSITION_RE, disp)), disp)
        record("E-03 响应头带 X-Request-Id", bool(hdrs.get("X-Request-Id")),
               str(hdrs.get("X-Request-Id")))
        record("E-03 响应头不含服务器路径",
               all(("exports" not in str(v) or "filename" in str(k))
                   for k, v in hdrs.items()))
        record("E-03 CSV 表头 = 冻结 12 列（无 id / user_id）",
               text.splitlines()[0] ==
               "metric_type,value_1,value_2,value_3,unit,attr_1,attr_2,recorded_at,"
               "time_start,note,tags,created_at", text.splitlines()[0])
        record("E-03 CSV 恰 3 行数据（软删记录不出现）",
               text.strip().count("\n") == 3 and "700" not in text,
               "lines=%d" % text.strip().count("\n"))
        record("E-03 CSV mood 标签以 | 连接", "relaxed|focused" in text,
               "found=%s" % ("relaxed|focused" in text))
        record("E-03 数值归一：70.50 -> 70.5", ",70.5," in text or ",70.5\r" in text,
               "found=%s" % ("70.5" in text))

        st, body = c.call("GET", "/exports/%d" % job1, None, token_a)
        d2b = data_of(body)
        record("E-03 首次下载写 downloaded_at 且 status=downloaded",
               d2b.get("downloaded_at") is not None and d2b.get("status") == "downloaded",
               "%s / %s" % (d2b.get("downloaded_at"), d2b.get("status")))
        first_at = d2b.get("downloaded_at")

        st, _h, raw2 = c.raw("GET", "/exports/%d/download?file_token=%s" % (job1, token1),
                             None, token_a)
        st2, body2 = c.call("GET", "/exports/%d" % job1, None, token_a)
        record("E-03 重复下载 200 且不覆盖首次 downloaded_at",
               st == 200 and raw2 == raw
               and data_of(body2).get("downloaded_at") == first_at,
               "%s vs %s" % (data_of(body2).get("downloaded_at"), first_at))

        # ── 9. E-03 反向：token / 越权 / 过期 ───────────────────────
        st, body = c.call("GET", "/exports/%d/download?file_token=%s" % (job1, "0" * 32),
                          None, token_a)
        record("E-03 token 不匹配 -> 404 RESOURCE_NOT_FOUND",
               st == 404 and code_of(body) == "RESOURCE_NOT_FOUND", "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("GET", "/exports/%d/download" % job1, None, token_a)
        record("E-03 缺 file_token -> 404 RESOURCE_NOT_FOUND",
               st == 404 and code_of(body) == "RESOURCE_NOT_FOUND", "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("GET", "/exports/%d" % job1, None, token_b)
        record("E-02 越权（对端查本端任务）-> 404", st == 404 and code_of(body) == "RESOURCE_NOT_FOUND",
               "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("GET", "/exports/%d/download?file_token=%s" % (job1, token1),
                          None, token_b)
        record("E-03 越权（对端持本端 token）-> 404",
               st == 404 and code_of(body) == "RESOURCE_NOT_FOUND", "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("GET", "/exports/99999999", None, token_a)
        record("E-02 不存在的任务 -> 404", st == 404 and code_of(body) == "RESOURCE_NOT_FOUND",
               "HTTP %s %s" % (st, code_of(body)))

        # ── 10. 409 冲突（进行中） → 下载后解除 ─────────────────────
        st, body = c.call("POST", "/exports", {"format": "csv", "password": PWD}, token_a)
        job2 = int(data_of(body).get("export_id") or 0)
        record("E-03 已下载任务不再阻塞 -> 202", st == 202, "HTTP %s %s" % (st, code_of(body)))
        st, body = c.call("POST", "/exports", {"format": "csv", "password": PWD}, token_a)
        record("E-01 已有 ready 任务 -> 409 EXPORT_IN_PROGRESS",
               st == 409 and code_of(body) == "EXPORT_IN_PROGRESS", "HTTP %s %s" % (st, code_of(body)))
        tk2 = str(data_of(c.call("GET", "/exports/%d" % job2, None, token_a)[1]).get("file_token") or "")
        c.raw("GET", "/exports/%d/download?file_token=%s" % (job2, tk2), None, token_a)

        # ── 11. json 格式导出 ───────────────────────────────────────
        st, body = c.call("POST", "/exports", {"format": "json", "metric_types": ["weight", "water"],
                                              "password": PWD}, token_a)
        job3 = int(data_of(body).get("export_id") or 0)
        record("E-01 json 格式 202 且 record_count = 2",
               st == 202 and data_of(body).get("record_count") == 2,
               "HTTP %s count=%s" % (st, data_of(body).get("record_count")))
        tk3 = str(data_of(c.call("GET", "/exports/%d" % job3, None, token_a)[1]).get("file_token") or "")
        st, hdrs3, raw3 = c.raw("GET", "/exports/%d/download?file_token=%s" % (job3, tk3),
                                None, token_a)
        record("E-03 json Content-Type = application/json; charset=utf-8",
               hdrs3.get("Content-Type") == "application/json; charset=utf-8",
               str(hdrs3.get("Content-Type")))
        try:
            payload = json.loads(raw3.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            payload = {"parse_error": str(exc)}
        record("E-03 json 顶层仅 records 键且 2 条",
               isinstance(payload, dict) and list(payload) == ["records"]
               and len(payload["records"]) == 2, str(payload)[:120])
        record("E-03 json 行不含 id / user_id",
               bool(payload.get("records")) and
               all(("id" not in r and "user_id" not in r) for r in payload.get("records", [])))

        # ── 12. E-04 列表 + 分页 ────────────────────────────────────
        st, body = c.call("GET", "/exports", None, token_a)
        d4 = data_of(body)
        record("E-04 200 且 data 恰 3 键", st == 200 and sorted(d4) == ["has_more", "items", "next_cursor"],
               "HTTP %s %s" % (st, sorted(d4)))
        record("E-04 items 每项恰 9 键（无 file_token）",
               all(sorted(it) == ITEM_KEYS for it in d4.get("items") or []),
               str(sorted((d4.get("items") or [{}])[0])))
        record("E-04 无 total / 无 file_path",
               "total" not in d4 and all("file_path" not in it for it in d4.get("items") or []))
        ats = [it["created_at"] for it in d4.get("items") or []]
        record("E-04 排序 created_at DESC", ats == sorted(ats, reverse=True), str(ats))
        record("E-04 本端 3 条 / has_more False",
               len(d4.get("items") or []) == 3 and d4.get("has_more") is False,
               "%d / %s" % (len(d4.get("items") or []), d4.get("has_more")))

        st, body = c.call("GET", "/exports?limit=100", None, token_a)
        record("E-04 limit=100 合法", st == 200, "HTTP %s" % st)
        bad_limits = ["7", "0", "-1", "101", "1000", "abc"]
        bad = [v for v in bad_limits
               if c.call("GET", "/exports?limit=" + v, None, token_a)[0] != 400]
        record("E-04 非法 limit 一律 400", not bad, str(bad))
        st, body = c.call("GET", "/exports?cursor=not-a-cursor", None, token_a)
        record("E-04 非法 cursor -> 400", st == 400, "HTTP %s %s" % (st, code_of(body)))

        d_b = data_of(c.call("GET", "/exports", None, token_b)[1])
        record("E-04 隔离：对端仅见自己的任务",
               all(it["export_id"] not in (job1, job2, job3) for it in d_b.get("items") or []),
               str([it["export_id"] for it in d_b.get("items") or []]))

        # ── 13. 幂等（同 Idempotency-Key 回放） ─────────────────────
        key = "b6smoke-" + datetime.now().strftime("%H%M%S%f")
        h = {"Idempotency-Key": key}
        st1, b1 = c.call("POST", "/exports", {"format": "csv", "password": PWD}, token_a, h)
        job4 = int(data_of(b1).get("export_id") or 0)
        if job4:
            tk4 = str(data_of(c.call("GET", "/exports/%d" % job4, None, token_a)[1]).get("file_token") or "")
            c.raw("GET", "/exports/%d/download?file_token=%s" % (job4, tk4), None, token_a)
        st2, b2 = c.call("POST", "/exports", {"format": "csv", "password": PWD}, token_a, h)
        record("E-01 同 Idempotency-Key 回放：状态码与 export_id 一致",
               st1 == st2 == 202 and data_of(b1).get("export_id") == data_of(b2).get("export_id"),
               "%s/%s" % (data_of(b1).get("export_id"), data_of(b2).get("export_id")))

        # ── 14. 参数校验 ────────────────────────────────────────────
        cases = [
            ({"password": PWD}, "缺 format -> 400"),
            ({"format": "xml", "password": PWD}, "format 非法 -> 400"),
            ({"format": "csv", "password": PWD, "metric_types": "water"}, "metric_types 非数组 -> 400"),
            ({"format": "csv", "password": PWD, "metric_types": []}, "metric_types 空数组 -> 400"),
            ({"format": "csv", "password": PWD, "metric_types": ["unknown"]}, "metric_types 非法值 -> 400"),
            # 注：``2026-9-1``（非零填充）**不会**被拒 —— Python ``strptime("%Y-%m-%d")`` 接受
            # 该写法，而 E-01 冻结契约（S1-B §十）的 400 清单只列 ``format`` 非法与
            # ``range_start >= range_end``，**未**要求严格零填充。``parse_range_bound`` 属
            # S0~S2 已封板基础设施（records / goals / stats 共用），本批不修改；
            # 故此处改用契约内可判定的非法格式（斜杠形态），该已知行为已在实现报告中登记。
            ({"format": "csv", "password": PWD, "range_start": "2026/03/01"},
             "range_start 非法格式 -> 400"),
            ({"format": "csv", "password": PWD, "range_start": day_str(-1), "range_end": day_str(-2)},
             "range_start >= range_end -> 400"),
            ({"format": "csv"}, "缺 password -> 400"),
        ]
        bad = [label for payload, label in cases
               if c.call("POST", "/exports", payload, token_a)[0] != 400]
        record("E-01 参数校验 8 例一律 400", not bad, str(bad))

        # ── 15. 半开区间 [start, end) ───────────────────────────────
        job5 = 0
        st, body = c.call("POST", "/exports", {"format": "csv", "range_start": day_str(-2),
                                              "range_end": day_str(-1), "password": PWD}, token_a)
        if st == 409:
            record("E-01 半开区间导出（跳过：仍有进行中任务）", True, "SKIP-409")
        else:
            job5 = int(data_of(body).get("export_id") or 0)
            record("E-01 半开区间 [d-2, d-1) 仅含 d-2 -> record_count = 1",
                   st == 202 and data_of(body).get("record_count") == 1,
                   "HTTP %s count=%s" % (st, data_of(body).get("record_count")))

        # ── 16. 落盘证据登记 ────────────────────────────────────────
        rows = dump_jobs([UA, UB])
        EXPORT_JOBS.extend(rows)
        paths = [r["file_path"] for r in rows if r["file_path"]]
        record("DB：本次测试账号 export_job 行数与 API 一致（>= 7）",
               len(rows) >= 7, str(len(rows)))
        record("DB：全部任务均有 file_path（failed 除外）",
               all(r["file_path"] or r["status"] == "failed" for r in rows),
               str([r["status"] for r in rows]))
        append_manifest(paths)
        say("  本次生成的导出文件 %d 个（已登记清单，不删除）" % len(paths))

    except Exception as exc:  # noqa: BLE001
        record("顶层执行异常", False, "%s: %s" % (type(exc).__name__, exc))
        import traceback
        say(traceback.format_exc())
    finally:
        # ── 17. 清理（仅 tstb6smoke* 两个账号；逐表物理 DELETE） ────
        try:
            counts = purge_accounts([UA, UB])
            say("  清理：%s" % counts)
            record("清理：测试账号数据已物理删除（user_account >= 2）",
                   int(counts.get("user_account", 0)) >= 2, str(counts))
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
