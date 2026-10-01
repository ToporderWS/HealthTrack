# -*- coding: utf-8 -*-
"""S2 第四批 —— **真实 HTTP 联调**（真启动 Flask + 真 MySQL，端到端闭环）。

用途：不依赖 Flask 测试客户端，用真实 HTTP 请求验证 G-01 ~ G-07 闭环：
``注册 → 建档/录入 → 目标创建 → 列表 → 修改 → 暂停/恢复 → 完成度 → 软删 → 重建``，
并核验统一响应壳、``X-Request-Id`` 一致性、软提示契约与跨用户隔离。

用法（必须用后端 venv 的 Python）::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch4_http_smoke.py

安全约定：
- **不打印任何 Token / 密码 / SECRET_KEY / DB 口令 / Authorization 头**；
- 测试密码**运行时随机生成**（符合现有密码策略），仅存活于当前进程内存，
  **不打印、不落盘、不写入任何配置**；注册与登录复用同一个随机密码；
- 测试账号统一前缀 ``tst`` 且**每次运行随机唯一**。

清理与残留语义（沿用第三批已验收的 4 项硬化 + 本批新增 1 项）：
1. ``cleanup()`` 与 Flask 子进程终止**都在 ``finally`` 中执行**；
2. Windows 下用 ``taskkill /F /T`` 终止 **Werkzeug reloader 派生**的整棵进程树；
3. 测试密码**运行时随机生成**；
4. ``residual()`` 只统计**本次运行**创建的测试数据（**不是**"整库必须为空"），
   数据库里原本存在的正常业务数据不会导致误 FAIL；
5. 额外启动一个**注入故障的隔离子进程**自证「异常路径仍完成清理」，子进程同样自清理。

数据库真实结构（只读核对结论，**不使用假设字段名**）：
本库**全部表均无外键、无 ON DELETE CASCADE**，关联依赖应用层维护，故清理必须
「先子表 → 再 user_account → 最后按 username 关联的锁定表」。
- ``user_account``：``id``(PK) / ``username``(UNIQUE)
- ``user_profile`` / ``health_record`` / ``health_goal`` / ``user_session`` / ``export_job``：``user_id``
- ``record_tag``：``user_id``（冗余）+ ``record_id``
- ``login_failure_state``：**仅 ``username``**（无 ``user_id``）

只读 + 自清理，**不修改数据库结构**、不产生 migration、不改动任何业务代码。
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pymysql  # noqa: E402

from app.core.config import load_config  # noqa: E402
from app.core.security import check_password_rule, now_local  # noqa: E402

HOST = "127.0.0.1"
PORT = 5000
BASE = f"http://{HOST}:{PORT}/api/v1"
HEALTH = f"{BASE}/health"

#: 测试账号前缀（**只用于生成/识别本次随机唯一用户名，不用作删除范围**）
PREFIX = "tst"

#: 8 张业务表（与 S1-B 数据库设计一致）
BUSINESS_TABLES = ("user_account", "user_profile", "health_record", "record_tag",
                   "health_goal", "user_session", "login_failure_state", "export_job")
#: 以 ``user_id`` 关联 ``user_account`` 的表
USER_ID_TABLES = ("user_profile", "health_record", "health_goal", "user_session", "export_job")

#: 故障注入用的环境变量（仅自证用；正常联调不设置）
FAULT_ENV = "SMOKE_INJECT_FAULT_STAGE"
#: 注入点：G-02 创建若干目标之后（此时账号 / 档案 / 记录 / 目标均已有测试数据）
FAULT_STAGE = "g02"
#: 子进程「异常后仍完成 cleanup」的证据标记
FAULT_OK_MARKER = "SMOKE_FAULT_CLEANUP_OK"
#: 子进程结果统计行前缀
FAULT_STATS_PREFIX = "SMOKE_FAULT_STATS "
#: 注入的异常特征串
FAULT_TAG = "SMOKE_FAULT_INJECTED"

#: 随机测试密码字符集（字母 + 数字，满足「必须同时含字母与数字」）
_PWD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

RESULTS: list = []


class InjectedFault(RuntimeError):
    """**故障注入专用**异常（仅用于验证异常路径的清理行为，不代表业务缺陷）。"""


# ── 断言与请求 ───────────────────────────────────────────────────────
def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)
    return bool(ok)


def request(method: str, url: str, payload=None, token=None, extra_headers=None):
    """发起真实 HTTP 请求；返回 ``(status, body_dict, headers)``。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"code": "<non-json>", "message": raw[:80]}
        return exc.code, body, dict(exc.headers)


def envelope_ok(status, body, headers, expect_status, expect_code) -> bool:
    """统一响应壳 + request_id 一致性 + 期望状态码/错误码。"""
    keys_ok = {"code", "message", "data", "request_id"} <= set(body)
    rid = str(body.get("request_id", ""))
    rid_ok = len(rid) == 32 and all(c in "0123456789abcdef" for c in rid)
    head_ok = headers.get("X-Request-Id") == rid
    return (status == expect_status and body.get("code") == expect_code
            and keys_ok and rid_ok and head_ok)


# ── 随机测试密码（仅内存，不打印 / 不落盘）────────────────────────────
def generate_test_password(length: int = 16) -> str:
    """运行时生成一个符合**现有密码策略**的随机测试密码（策略本身不修改，仅调用自校验）。"""
    rng = secrets.SystemRandom()
    for _ in range(64):
        pwd = "".join(rng.choice(_PWD_ALPHABET) for _ in range(length))
        if check_password_rule(pwd) is None:
            return pwd
    raise RuntimeError("无法生成符合密码策略的随机测试密码")  # pragma: no cover


def register_and_login(username: str, password: str) -> str:
    """注册并登录，返回 access_token（**不打印**）。"""
    status, body, _ = request("POST", f"{BASE}/auth/register", {
        "username": username, "password": password,
        "agreement_version": "v1.0", "agreement_accepted": True,
    })
    if status != 201:
        raise RuntimeError(f"注册失败 HTTP {status} {body.get('code')}")
    status, body, _ = request("POST", f"{BASE}/auth/login",
                              {"username": username, "password": password})
    if status != 200:
        raise RuntimeError(f"登录失败 HTTP {status} {body.get('code')}")
    return ((body.get("data") or {}).get("tokens") or {}).get("access_token")


# ── 时间工具（G-07 窗口口径）────────────────────────────────────────
def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _now_ts() -> datetime:
    return now_local().replace(microsecond=0)


def _day_at(offset: int, hour: int = 9, minute: int = 0) -> datetime:
    day = now_local().date() + timedelta(days=offset)
    return datetime.combine(day, dtime(hour, minute))


# ── 数据库：连接 / 定位 / 清理 / 残留 / 非测试数据快照 ────────────────
def _connect(cfg):
    return pymysql.connect(
        host=cfg["MYSQL_HOST"], port=int(cfg["MYSQL_PORT"]),
        user=cfg["MYSQL_USER"], password=cfg["MYSQL_PASSWORD"],
        database=cfg["MYSQL_DB"], charset=cfg["MYSQL_CHARSET"], autocommit=True,
    )


def _ph(n: int) -> str:
    return ",".join(["%s"] * n)


def _new_counts() -> dict:
    return {t: 0 for t in BUSINESS_TABLES}


def collect_targets(cfg, usernames) -> dict:
    """按**本次运行生成的唯一用户名**定位其 ``user_id`` 与 ``health_record.id`` 快照。"""
    targets = {"user_ids": [], "record_ids": [], "goal_ids": []}
    names = [u for u in (usernames or []) if u]
    if not names:
        return targets
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM user_account WHERE username IN ({_ph(len(names))})", names)
            ids = [int(r[0]) for r in cur.fetchall()]
            if ids:
                ph_ids = _ph(len(ids))
                cur.execute(f"SELECT id FROM health_record WHERE user_id IN ({ph_ids})", ids)
                targets["record_ids"] = [int(r[0]) for r in cur.fetchall()]
                cur.execute(f"SELECT id FROM health_goal WHERE user_id IN ({ph_ids})", ids)
                targets["goal_ids"] = [int(r[0]) for r in cur.fetchall()]
            targets["user_ids"] = ids
    finally:
        conn.close()
    return targets


def cleanup(cfg, usernames) -> dict:
    """删除**本次联调创建**的测试账号及其全部关联数据；返回各表删除行数。

    - 范围：仅本次运行随机生成的唯一用户名（**不使用 ``LIKE 'tst%'`` 作为删除范围**）；
    - 顺序：**先子表 → 再 ``user_account`` → 最后 ``login_failure_state``**（本库无 CASCADE）；
    - ``record_tag`` 同时按 ``user_id`` 与 ``record_id`` 删除，避免孤儿标签；
    - **不使用 TRUNCATE**、不做整表删除、不改表结构。
    """
    removed = _new_counts()
    names = [u for u in (usernames or []) if u]
    if not names:
        return removed
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM user_account WHERE username IN ({_ph(len(names))})", names)
            ids = [int(r[0]) for r in cur.fetchall()]
            rec_ids: list = []
            if ids:
                ph_ids = _ph(len(ids))
                cur.execute(f"SELECT id FROM health_record WHERE user_id IN ({ph_ids})", ids)
                rec_ids = [int(r[0]) for r in cur.fetchall()]
                if rec_ids:
                    removed["record_tag"] += cur.execute(
                        f"DELETE FROM record_tag WHERE user_id IN ({ph_ids})"
                        f" OR record_id IN ({_ph(len(rec_ids))})", ids + rec_ids)
                else:
                    removed["record_tag"] += cur.execute(
                        f"DELETE FROM record_tag WHERE user_id IN ({ph_ids})", ids)
                for table in ("health_record", "health_goal", "export_job",
                              "user_profile", "user_session"):
                    removed[table] += cur.execute(
                        f"DELETE FROM {table} WHERE user_id IN ({ph_ids})", ids)
                removed["user_account"] += cur.execute(
                    f"DELETE FROM user_account WHERE id IN ({ph_ids})", ids)
            removed["login_failure_state"] += cur.execute(
                f"DELETE FROM login_failure_state WHERE username IN ({_ph(len(names))})", names)
    finally:
        conn.close()
    return removed


def residual(cfg, usernames, targets=None) -> dict:
    """**本次 tst 联调测试数据残留行数**（只统计本次运行创建的数据）。"""
    targets = targets or {}
    snap_ids = [int(i) for i in (targets.get("user_ids") or [])]
    snap_recs = [int(i) for i in (targets.get("record_ids") or [])]
    names = [u for u in (usernames or []) if u]

    counts = _new_counts()
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            live_ids: list = []
            if names:
                ph = _ph(len(names))
                cur.execute(f"SELECT id FROM user_account WHERE username IN ({ph})", names)
                live_ids = [int(r[0]) for r in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM user_account WHERE username IN ({ph})", names)
                counts["user_account"] = int(cur.fetchone()[0])
                cur.execute(
                    f"SELECT COUNT(*) FROM login_failure_state WHERE username IN ({ph})", names)
                counts["login_failure_state"] = int(cur.fetchone()[0])
            all_ids = sorted(set(snap_ids) | set(live_ids))
            if all_ids:
                ph_ids = _ph(len(all_ids))
                for table in USER_ID_TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id IN ({ph_ids})",
                                all_ids)
                    counts[table] = int(cur.fetchone()[0])
                if snap_recs:
                    cur.execute(
                        f"SELECT COUNT(*) FROM record_tag WHERE user_id IN ({ph_ids})"
                        f" OR record_id IN ({_ph(len(snap_recs))})", all_ids + snap_recs)
                else:
                    cur.execute(f"SELECT COUNT(*) FROM record_tag WHERE user_id IN ({ph_ids})",
                                all_ids)
                counts["record_tag"] = int(cur.fetchone()[0])
            elif snap_recs:
                cur.execute(
                    f"SELECT COUNT(*) FROM record_tag WHERE record_id IN ({_ph(len(snap_recs))})",
                    snap_recs)
                counts["record_tag"] = int(cur.fetchone()[0])
    finally:
        conn.close()
    counts["total"] = sum(counts[t] for t in BUSINESS_TABLES)
    return counts


def tst_residual(cfg) -> dict:
    """全库 ``tst`` 前缀残留（含**历史遗留**）—— 补充安全网。"""
    counts = _new_counts()
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM user_account WHERE username LIKE %s", (f"{PREFIX}%",))
            ids = [int(r[0]) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) FROM user_account WHERE username LIKE %s", (f"{PREFIX}%",))
            counts["user_account"] = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM login_failure_state WHERE username LIKE %s",
                        (f"{PREFIX}%",))
            counts["login_failure_state"] = int(cur.fetchone()[0])
            if ids:
                ph_ids = _ph(len(ids))
                cur.execute(f"SELECT id FROM health_record WHERE user_id IN ({ph_ids})", ids)
                rec_ids = [int(r[0]) for r in cur.fetchall()]
                for table in USER_ID_TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id IN ({ph_ids})", ids)
                    counts[table] = int(cur.fetchone()[0])
                if rec_ids:
                    cur.execute(
                        f"SELECT COUNT(*) FROM record_tag WHERE user_id IN ({ph_ids})"
                        f" OR record_id IN ({_ph(len(rec_ids))})", ids + rec_ids)
                else:
                    cur.execute(f"SELECT COUNT(*) FROM record_tag WHERE user_id IN ({ph_ids})", ids)
                counts["record_tag"] = int(cur.fetchone()[0])
    finally:
        conn.close()
    counts["total"] = sum(counts[t] for t in BUSINESS_TABLES)
    return counts


def non_test_counts(cfg) -> dict:
    """**非 tst（真实业务）数据**行数快照 —— 用于证明 cleanup 未误删正常数据。"""
    counts = _new_counts()
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM user_account WHERE username LIKE %s", (f"{PREFIX}%",))
            ids = [int(r[0]) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) FROM user_account WHERE username NOT LIKE %s",
                        (f"{PREFIX}%",))
            counts["user_account"] = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM login_failure_state WHERE username NOT LIKE %s",
                        (f"{PREFIX}%",))
            counts["login_failure_state"] = int(cur.fetchone()[0])
            for table in USER_ID_TABLES + ("record_tag",):
                if ids:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE user_id NOT IN ({_ph(len(ids))})", ids)
                else:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cur.fetchone()[0])
    finally:
        conn.close()
    return counts


def goal_db_row(cfg, goal_id: int):
    """直查 ``health_goal`` 物理行（用于核验软删三件事）。"""
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, user_id, goal_type, status, is_deleted, deleted_at, "
                        "deleted_marker, target_value FROM health_goal WHERE id=%s",
                        (int(goal_id),))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": int(row[0]), "user_id": int(row[1]), "goal_type": row[2], "status": int(row[3]),
            "is_deleted": int(row[4]), "deleted_at": row[5], "deleted_marker": int(row[6]),
            "target_value": float(row[7])}


def _residual_safe(cfg, usernames, targets=None):
    try:
        return residual(cfg, usernames, targets), None
    except Exception as exc:
        print(f"  !! residual 读取失败：{type(exc).__name__}: {exc}", flush=True)
        return None, exc


def _tst_residual_safe(cfg):
    try:
        return tst_residual(cfg), None
    except Exception as exc:
        print(f"  !! 全库 tst 残留读取失败：{type(exc).__name__}: {exc}", flush=True)
        return None, exc


def _non_test_safe(cfg):
    try:
        return non_test_counts(cfg), None
    except Exception as exc:
        print(f"  !! 非测试数据快照读取失败：{type(exc).__name__}: {exc}", flush=True)
        return None, exc


def _nonzero(counts) -> str:
    if not counts:
        return "n/a"
    parts = [f"{k}={v}" for k, v in counts.items() if k != "total" and v]
    return ", ".join(parts) if parts else "全部为 0"


# ── 进程管理 ─────────────────────────────────────────────────────────
def _port_in_use() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def _wait_server_up(proc, tries: int = 40) -> bool:
    if proc is None:
        return False
    for _ in range(tries):
        time.sleep(0.5)
        try:
            status, _body, _h = request("GET", HEALTH)
            if status == 200:
                return True
        except Exception:
            pass
        if proc.poll() is not None:
            return False
    return False


def _terminate(proc):
    """终止**本次启动的** Flask 子进程及其 reloader 派生的全部子进程。

    ``app.run(debug=True)``（development 默认）会启用 Werkzeug reloader，
    单纯 ``proc.terminate()`` 只结束外层父进程，真正的服务子进程会继续占用 5000 端口；
    因此在 Windows 上使用 ``taskkill /F /T`` 终止整棵进程树。

    **只作用于本脚本 ``Popen`` 得到的 PID**，不会影响任何非本次启动的进程。
    """
    if proc is None:
        return None
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        return None
    except Exception as exc:
        return exc


def _wait_port_released(timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_in_use():
            return True
        time.sleep(0.25)
    return not _port_in_use()


# ── 用例主体 ─────────────────────────────────────────────────────────
def _fault_gate(stage: str, fault_stage) -> None:
    """故障注入闸门：仅当显式指定 ``fault_stage`` 等于当前阶段时抛异常。"""
    if fault_stage and stage == fault_stage:
        raise InjectedFault(f"{FAULT_TAG}@{stage}")


def run_cases(cfg, password: str, fault_stage=None, created=None) -> None:  # noqa: C901
    """执行全部真实 HTTP 用例（服务需已就绪）。密码仅在内存中传递。"""
    users = created if created is not None else []
    user = f"{PREFIX}a{secrets.token_hex(3)}"
    peer = f"{PREFIX}b{secrets.token_hex(3)}"
    users.extend([user, peer])

    token = register_and_login(user, password)
    peer_token = register_and_login(peer, password)
    H = {"Authorization": f"Bearer {token}"}
    PH = {"Authorization": f"Bearer {peer_token}"}

    # ── 1 G-01 空列表 ──
    print("\n[1] G-01 目标列表（空）")
    status, body, headers = request("GET", f"{BASE}/goals", token=token)
    check("G-01 200 + OK + 响应壳", envelope_ok(status, body, headers, 200, "OK"), f"HTTP {status}")
    check("G-01 无目标 → items: []（**不是 404**）", (body.get("data") or {}).get("items") == [])

    status, body, headers = request("GET", f"{BASE}/goals", token=token,
                                    extra_headers={"X-Probe": "1"})
    check("G-01 goal_type 非法 → 400 INVALID_PARAM",
          request("GET", f"{BASE}/goals?goal_type=bp", token=token)[0] == 400)
    check("G-01 未认证 → 401",
          request("GET", f"{BASE}/goals")[0] == 401
          and request("GET", f"{BASE}/goals")[1].get("code") == "UNAUTHENTICATED")

    # ── 2 准备档案 + 记录（供 G-07 使用）──
    print("\n[2] 准备档案与健康记录（真实 HTTP）")
    status, body, _ = request("PUT", f"{BASE}/profile", {
        "nickname": "目标联调", "gender": 1, "birth_date": "1995-03-18",
        "height_cm": 175.0, "initial_weight_kg": 72.5,
    }, token=token)
    check("P-02 建档 200", status == 200, f"HTTP {status}")
    status, body, _ = request("PUT", f"{BASE}/profile", {
        "nickname": "目标联调", "gender": 1, "birth_date": "1995-03-18", "height_cm": 180.0,
    }, token=peer_token)
    check("P-02 对端建档 200", status == 200, f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/records", {
        "metric_type": "weight", "value_1": 70.4, "recorded_at": _fmt(_day_at(-1)),
    }, token=token)
    check("R-01 体重记录（供 auto_start_weight）201", status == 201, f"HTTP {status}")

    for value in (1000, 500):
        status, _, _ = request("POST", f"{BASE}/records", {
            "metric_type": "water", "value_1": value, "recorded_at": _fmt(_now_ts()),
        }, token=token)
        assert status == 201, status
    check("R-01 饮水记录 2 条（今日累计 1500）", True)

    for value in (30, 20):
        status, _, _ = request("POST", f"{BASE}/records", {
            "metric_type": "sport", "value_1": value, "attr_1": "running",
            "recorded_at": _fmt(_now_ts()),
        }, token=token)
        assert status == 201, status
    check("R-01 运动记录 2 条（本周累计 50 分钟）", True)

    end = _now_ts()
    status, _, _ = request("POST", f"{BASE}/records", {
        "metric_type": "sleep", "value_1": 4,
        "time_start": _fmt(end - timedelta(hours=7, minutes=30)),
        "recorded_at": _fmt(end),
    }, token=token)
    check("R-01 睡眠记录（派生 7.5 小时）201", status == 201, f"HTTP {status}")

    # ── 3 G-02 创建 ──
    print("\n[3] G-02 创建目标（真实 HTTP POST）")
    status, body, headers = request("POST", f"{BASE}/goals", {
        "goal_type": "water", "target_value": 2000,
    }, token=token)
    water = (body.get("data") or {}).get("goal") or {}
    check("G-02 water 201 + period_type/unit 服务端强制",
          envelope_ok(status, body, headers, 201, "OK")
          and water.get("period_type") == "daily" and water.get("unit") == "ml",
          f"HTTP {status}")
    check("G-02 message = 目标已创建", body.get("message") == "目标已创建")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "water", "target_value": 2500,
    }, token=token)
    check("G-02 同类在用目标 → 409 GOAL_TYPE_EXISTS",
          status == 409 and body.get("code") == "GOAL_TYPE_EXISTS", f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "sport", "target_value": 150, "attr_1": "min", "period_type": "daily",
    }, token=token)
    check("G-02 period_type 不一致 → 422",
          status == 422 and body.get("code") == "VALIDATION_FAILED", f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "sport", "target_value": 150,
    }, token=token)
    check("G-02 sport 缺 attr_1 → 422",
          status == 422 and any(e.get("field") == "attr_1"
                                for e in (body.get("errors") or [])), f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "sleep", "target_value": 30,
    }, token=token)
    check("G-02 目标值不可能 → 422 硬拦截",
          status == 422 and body.get("code") == "VALIDATION_FAILED", f"HTTP {status}")

    status, body, headers = request("POST", f"{BASE}/goals", {
        "goal_type": "sleep", "target_value": 20,
    }, token=token)
    check("G-02 超常见范围 → 200 SOFT_WARNING（本次不写入）",
          envelope_ok(status, body, headers, 200, "SOFT_WARNING")
          and (body.get("data") or {}).get("requires_confirm") is True, f"HTTP {status}")
    check("G-02 软提示不带 errors[]（独立 warnings[] 体系）",
          "errors" not in body and (body.get("data") or {}).get("warnings"))
    _items_now = request("GET", f"{BASE}/goals", token=token)[1]["data"]["items"]
    check("G-02 软提示未写入（列表不含该 sleep:20 目标）",
          all(not (i.get("goal_type") == "sleep" and i.get("target_value") == 20)
              for i in _items_now))

    status, body, headers = request("POST", f"{BASE}/goals", {
        "goal_type": "sleep", "target_value": 8,
    }, token=token)
    sleep_goal = (body.get("data") or {}).get("goal") or {}
    check("G-02 sleep 201 + unit=hour + period_type=daily",
          envelope_ok(status, body, headers, 201, "OK")
          and sleep_goal.get("unit") == "hour", f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "sport", "target_value": 150, "attr_1": "min",
    }, token=token)
    sport_goal = (body.get("data") or {}).get("goal") or {}
    check("G-02 sport(min) 201 + unit=min + period_type=weekly",
          status == 201 and sport_goal.get("unit") == "min"
          and sport_goal.get("period_type") == "weekly", f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "weight", "target_value": 66.0, "auto_start_weight": True,
        "target_date": "2026-12-31",
    }, token=token)
    weight_goal = (body.get("data") or {}).get("goal") or {}
    check("G-02 weight(auto_start_weight) 201 + 起始体重取最近记录 70.4",
          status == 201 and weight_goal.get("start_weight_kg") == 70.4, f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "weight", "target_value": 70.4, "start_weight_kg": 70.4,
    }, token=token)
    check("G-02 weight 目标值 == 起始体重 → 422（且未创建第 2 条 weight）",
          status == 422, f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "water", "target_value": 2000, "user_id": 1,
    }, token=token)
    check("G-02 携带 user_id → 400 INVALID_PARAM",
          status == 400 and body.get("code") == "INVALID_PARAM", f"HTTP {status}")

    # ★ 故障注入点（仅自证用；正常联调下 fault_stage 为 None，此处为空操作）
    _fault_gate("g02", fault_stage)

    # ── 4 G-01 列表与过滤 ──
    print("\n[4] G-01 列表 / 过滤 / 排序")
    status, body, headers = request("GET", f"{BASE}/goals", token=token)
    items = (body.get("data") or {}).get("items") or []
    check("G-01 200 + 4 类目标 + goal_type ASC 排序",
          envelope_ok(status, body, headers, 200, "OK")
          and [i["goal_type"] for i in items] == ["sleep", "sport", "water", "weight"],
          f"HTTP {status}")
    check("G-01 不暴露 is_deleted / deleted_marker / deleted_at",
          all(not ({"is_deleted", "deleted_marker", "deleted_at"} & set(i)) for i in items))
    check("G-01 条目字段与契约一致",
          all({"id", "goal_type", "period_type", "target_value", "unit", "attr_1",
               "start_weight_kg", "start_date", "target_date", "status", "status_text",
               "created_at"} == set(i) for i in items))

    status, body, _ = request("GET", f"{BASE}/goals?goal_type=water", token=token)
    check("G-01 goal_type 过滤生效",
          [i["goal_type"] for i in body["data"]["items"]] == ["water"])

    status, body, _ = request("GET", f"{BASE}/goals?include_history=true", token=token)
    check("G-01 include_history=true 仍返回 4 条在用目标（暂无历史）",
          len(body["data"]["items"]) == 4)

    # ── 5 G-07 完成度 ──
    print("\n[5] G-07 目标完成度（真实 HTTP GET）")
    status, body, headers = request("GET", f"{BASE}/goals/progress", token=token)
    prog = {i["goal_type"]: i for i in (body.get("data") or {}).get("items") or []}
    check("G-07 200 + 4 条完成度", envelope_ok(status, body, headers, 200, "OK")
          and len(prog) == 4, f"HTTP {status}")
    check("G-07 water 当日累计 1500/2000 = 75.0 + remaining 500 ml",
          prog.get("water", {}).get("current_value") == 1500
          and prog["water"]["progress_percent"] == 75.0
          and prog["water"]["remaining_text"] == "还差 500 ml")
    check("G-07 sport 本周累计 50/150 = 33.3（weekly, this_week）",
          prog.get("sport", {}).get("current_value") == 50
          and prog["sport"]["progress_percent"] == 33.3
          and prog["sport"]["period_label"] == "this_week")
    check("G-07 weight (70.4→66.0，当前 70.4) = 0.0% + rate 恒 null",
          prog.get("weight", {}).get("progress_percent") == 0.0
          and prog["weight"]["rate"] is None
          and prog["weight"]["period_label"] == "overall")
    check("G-07 sleep 派生 7.5/8 = 93.8（today）",
          prog.get("sleep", {}).get("current_value") == 7.5
          and prog["sleep"]["progress_percent"] == 93.8)
    check("G-07 water 有 rate（daily）；weight 无 rate",
          isinstance(prog["water"].get("rate"), dict)
          and prog["water"]["rate"]["days_recorded"] == 1
          and prog["water"]["rate"]["reached_rate_percent"] == 0.0)

    status, body, _ = request("GET", f"{BASE}/goals/progress?rate_window=7", token=token)
    check("G-07 rate_window=7 生效", body["data"]["items"][0]["rate"]["window_days"] == 7)
    status, body, _ = request("GET", f"{BASE}/goals/progress?rate_window=45", token=token)
    check("G-07 rate_window 非法 → 400 INVALID_PARAM",
          status == 400 and body.get("code") == "INVALID_PARAM", f"HTTP {status}")

    status, body, _ = request("GET", f"{BASE}/goals/progress?goal_id={weight_goal['id']}",
                              token=token)
    check("G-07 goal_id 只返回指定目标",
          [i["goal_id"] for i in body["data"]["items"]] == [weight_goal["id"]])

    status, body, _ = request("GET", f"{BASE}/goals/progress?goal_id=99999999", token=token)
    check("G-07 goal_id 不存在 → 404 RESOURCE_NOT_FOUND",
          status == 404 and body.get("code") == "RESOURCE_NOT_FOUND", f"HTTP {status}")

    status, body, _ = request("GET", f"{BASE}/goals/progress?goal_id={water['id']}",
                              token=peer_token)
    check("G-07 跨用户 goal_id → 404（不泄露资源是否存在）", status == 404, f"HTTP {status}")

    # ── 6 G-03 修改 ──
    print("\n[6] G-03 修改目标（真实 HTTP PATCH）")
    status, body, headers = request("PATCH", f"{BASE}/goals/{water['id']}", {
        "target_value": 2500,
    }, token=token)
    check("G-03 200 + 目标值已更新",
          envelope_ok(status, body, headers, 200, "OK")
          and (body.get("data") or {})["goal"]["target_value"] == 2500, f"HTTP {status}")

    status, body, _ = request("PATCH", f"{BASE}/goals/{water['id']}", {
        "goal_type": "water", "target_value": 2500,
    }, token=token)
    check("G-03 goal_type 出现（值相同）→ 422",
          status == 422 and any(e.get("field") == "goal_type"
                                for e in (body.get("errors") or [])), f"HTTP {status}")

    status, body, _ = request("PATCH", f"{BASE}/goals/{weight_goal['id']}", {
        "start_weight_kg": 70.0,
    }, token=token)
    check("G-03 start_weight_kg 不可修改 → 422",
          status == 422 and any(e.get("field") == "start_weight_kg"
                                for e in (body.get("errors") or [])), f"HTTP {status}")

    status, body, _ = request("PATCH", f"{BASE}/goals/{water['id']}", {
        "target_value": 2500,
    }, token=peer_token)
    check("G-03 跨用户 → 404", status == 404, f"HTTP {status}")

    # ── 7 G-04 / G-05 状态机 ──
    print("\n[7] G-04 暂停 / G-05 恢复（真实 HTTP POST）")
    status, body, headers = request("POST", f"{BASE}/goals/{water['id']}/pause", token=token)
    check("G-04 暂停 200 + changed true",
          envelope_ok(status, body, headers, 200, "OK")
          and body["data"] == {"id": water["id"], "status": 0, "changed": True}, f"HTTP {status}")
    status, body, _ = request("POST", f"{BASE}/goals/{water['id']}/pause", token=token)
    check("G-04 幂等：已暂停再调 → changed false",
          status == 200 and body["data"]["changed"] is False, f"HTTP {status}")

    status, body, _ = request("GET", f"{BASE}/goals", token=token,
                              extra_headers={})
    paused_item = next(i for i in body["data"]["items"] if i["id"] == water["id"])
    check("G-04 status_text = paused（中性）", paused_item["status_text"] == "paused")

    status, body, _ = request("GET", f"{BASE}/goals?include_paused=false", token=token)
    check("G-04 include_paused=false 过滤掉暂停目标",
          all(i["id"] != water["id"] for i in body["data"]["items"]))

    status, body, headers = request("POST", f"{BASE}/goals/{water['id']}/resume", token=token)
    check("G-05 恢复 200 + changed true",
          envelope_ok(status, body, headers, 200, "OK")
          and body["data"]["changed"] is True, f"HTTP {status}")
    status, body, _ = request("POST", f"{BASE}/goals/{water['id']}/resume", token=token)
    check("G-05 幂等：已进行中再调 → changed false",
          status == 200 and body["data"]["changed"] is False, f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals/{water['id']}/pause", token=peer_token)
    check("G-04/G-05 跨用户 → 404", status == 404, f"HTTP {status}")

    # ── 8 暂停目标仍返回完整完成度（D-G3）──
    print("\n[8] D-G3 暂停目标仍返回完整完成度")
    request("POST", f"{BASE}/goals/{water['id']}/pause", token=token)
    status, body, _ = request("GET", f"{BASE}/goals/progress?goal_id={water['id']}", token=token)
    paused_prog = (body.get("data") or {}).get("items")[0]
    check("D-G3 暂停目标 status=0 但仍返回完整完成度",
          paused_prog["status"] == 0 and paused_prog["current_value"] == 1000 + 500
          and paused_prog["progress_percent"] == 60.0, str(paused_prog["progress_percent"]))
    request("POST", f"{BASE}/goals/{water['id']}/resume", token=token)

    # ── 9 G-06 软删 ──
    print("\n[9] G-06 软删（真实 HTTP DELETE）")
    status, body, headers = request("DELETE", f"{BASE}/goals/{sleep_goal['id']}", token=token)
    check("G-06 200 + deleted_count 1",
          envelope_ok(status, body, headers, 200, "OK")
          and body["data"] == {"deleted_count": 1}, f"HTTP {status}")

    row = goal_db_row(cfg, sleep_goal["id"])
    check("G-06 ★ 软删三件事齐全（is_deleted=1 / deleted_at 非空 / deleted_marker=id）",
          row is not None and row["is_deleted"] == 1 and row["deleted_at"] is not None
          and row["deleted_marker"] == row["id"], str(row))
    check("G-06 物理行保留（未物理删除）", row is not None)

    status, body, _ = request("GET", f"{BASE}/goals", token=token)
    check("G-06 软删后默认列表不可见",
          all(i["id"] != sleep_goal["id"] for i in body["data"]["items"]))
    status, body, _ = request("GET", f"{BASE}/goals?include_history=true", token=token)
    archived = [i for i in body["data"]["items"] if i["id"] == sleep_goal["id"]]
    check("G-06 历史行 status_text = archived 且只读展示",
          len(archived) == 1 and archived[0]["status_text"] == "archived")

    status, body, _ = request("DELETE", f"{BASE}/goals/{sleep_goal['id']}", token=token)
    check("G-06 重复删除 → 404 RESOURCE_NOT_FOUND",
          status == 404 and body.get("code") == "RESOURCE_NOT_FOUND", f"HTTP {status}")
    status, body, _ = request("PATCH", f"{BASE}/goals/{sleep_goal['id']}",
                              {"target_value": 9}, token=token)
    check("G-06 历史目标不可编辑（G-03）→ 404", status == 404, f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "sleep", "target_value": 8,
    }, token=token)
    rebuilt = (body.get("data") or {}).get("goal") or {}
    check("G-06 ★ 软删后同类型可**立即重建**（deleted_marker 释放唯一约束）",
          status == 201 and rebuilt.get("id") != sleep_goal["id"], f"HTTP {status}")
    check("G-06 重建行 deleted_marker 归 0",
          goal_db_row(cfg, rebuilt["id"])["deleted_marker"] == 0)

    status, body, _ = request("DELETE", f"{BASE}/goals/{sleep_goal['id']}", token=peer_token)
    check("G-06 跨用户 → 404", status == 404, f"HTTP {status}")

    # ── 10 跨用户隔离与注入 ──
    print("\n[10] 跨用户隔离 / user_id 注入")
    status, body, _ = request("GET", f"{BASE}/goals", token=peer_token)
    check("隔离：对端列表不含本端目标（对端 0 条）", body["data"]["items"] == [])
    status, body, _ = request("GET", f"{BASE}/goals?user_id=1", token=token)
    check("user_id 注入（query）→ 400 INVALID_PARAM",
          status == 400 and body.get("code") == "INVALID_PARAM", f"HTTP {status}")
    status, body, _ = request("POST", f"{BASE}/goals", {
        "goal_type": "water", "target_value": 2000, "user_id": 1,
    }, token=token)
    check("user_id 注入（body）→ 400", status == 400, f"HTTP {status}")
    status, body, _ = request("GET", f"{BASE}/goals")
    check("未认证全体 → 401 UNAUTHENTICATED",
          status == 401 and body.get("code") == "UNAUTHENTICATED", f"HTTP {status}")


# ── 一次完整会话（启动 → 用例 → finally：终止 + 清理）────────────────
def run_session(cfg, password: str, fault_stage=None) -> dict:
    """启动 Flask、执行用例，并**在 finally 中**终止子进程与清理测试数据。"""
    global RESULTS
    saved = RESULTS
    RESULTS = []

    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8"}
    created: list = []
    proc = None
    failure = None
    proc_failure = None
    cleanup_failure = None
    snapshot_failure = None
    targets: dict = {"user_ids": [], "record_ids": [], "goal_ids": []}
    removed = _new_counts()
    released = False
    injected = False

    try:
        print("\n[0] 服务启动")
        if _port_in_use():
            check("5000 端口空闲（不干扰外部已运行服务）", False,
                  "端口已被占用：拒绝启动，且**不会终止任何非本脚本启动的进程**")
            raise RuntimeError(f"{PORT} 端口已被其他进程占用，联调终止（不触碰第三方进程）")
        check("5000 端口空闲（不干扰外部已运行服务）", True)
        proc = subprocess.Popen(
            [sys.executable, "wsgi.py"], cwd=BACKEND, env=env,
            # 子进程输出必须**丢弃**：若用 PIPE 且不读取，日志会写满管道缓冲区导致阻塞。
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not _wait_server_up(proc):
            check("Flask 真实启动并响应 /api/v1/health", False, "超时未就绪")
            raise RuntimeError("Flask 服务未能在超时内启动，联调终止")
        check("Flask 真实启动并响应 /api/v1/health", True)
        run_cases(cfg, password, fault_stage, created)
    except Exception as exc:
        failure = exc
        injected = isinstance(exc, InjectedFault)
        print(f"\n  !! 联调中断：{type(exc).__name__}: {str(exc)[:120]}", flush=True)
    finally:
        proc_failure = _terminate(proc)
        if proc_failure is not None:
            print(f"  !! Flask 子进程终止异常：{type(proc_failure).__name__}: {proc_failure}",
                  flush=True)
        released = _wait_port_released()
        try:
            targets = collect_targets(cfg, created)
        except Exception as exc:
            snapshot_failure = exc
            print(f"  !! 测试账号 ID 快照失败：{type(exc).__name__}: {exc}", flush=True)
        try:
            removed = cleanup(cfg, created)
        except Exception as exc:
            cleanup_failure = exc
            print(f"  !! cleanup 失败：{type(cleanup_failure).__name__}: {cleanup_failure}",
                  flush=True)
        print(f"  · cleanup 明细：{_nonzero(removed)}"
              f"（合计 {sum(removed.values())} 行）", flush=True)

    session = {
        "results": list(RESULTS),
        "usernames": list(created),
        "targets": targets,
        "failure": failure,
        "injected": injected,
        "proc_failure": proc_failure,
        "cleanup_failure": cleanup_failure,
        "snapshot_failure": snapshot_failure,
        "removed": removed,
        "released": released,
    }
    saved.extend(RESULTS)
    RESULTS = saved
    return session


# ── 异常路径自证（隔离子进程注入故障）────────────────────────────────
def _parse_stats(out: str) -> dict:
    info: dict = {}
    for line in out.splitlines():
        if line.startswith(FAULT_STATS_PREFIX):
            for token in line[len(FAULT_STATS_PREFIX):].strip().split():
                if "=" in token:
                    k, _s, v = token.partition("=")
                    info[k] = v
    return info


def _split_csv(raw) -> list:
    return [p for p in str(raw or "").split(",") if p]


def fault_selftest(attempts: int = 2):
    """在**独立子进程**中注入异常，自证「异常路径下 cleanup 仍在 finally 执行」。

    - 子进程使用独立的随机密码与独立随机 ``tst`` 账号，且自身也执行 finally 清理；
    - 子进程检测到 ``SMOKE_INJECT_FAULT_STAGE`` 后只做一次注入，**不会再次调用本函数**
      （见 ``main`` 的 ``fault_stage`` 分支），**不存在递归**。
    """
    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8",
           FAULT_ENV: FAULT_STAGE}
    last = "未执行"
    for _ in range(max(1, attempts)):
        if not _wait_port_released(5.0):
            last = f"{PORT} 端口未释放，无法启动自证子进程"
            time.sleep(1.0)
            continue
        try:
            cp = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                cwd=str(ROOT), env=env, timeout=300,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            last = f"子进程执行失败 {type(exc).__name__}"
            time.sleep(1.5)
            continue
        out = (cp.stdout or b"").decode("utf-8", "replace")
        info = _parse_stats(out)
        if FAULT_TAG not in out:
            last = "故障未注入（子进程未到达注入点，通常是服务未就绪）"
            time.sleep(1.5)
            continue
        if cp.returncode == 0:
            last = "注入异常后子进程仍返回 0（异常被吞或未被判定为失败）"
            continue
        if FAULT_OK_MARKER not in out:
            last = "子进程异常退出，但未在 finally 完成清理"
            continue
        summary = (f"子进程 exit={cp.returncode}，自报 {info.get('ok', '?')}/{info.get('total', '?')}"
                   f" PASS，cleanup {info.get('removed', '?')} 行，"
                   f"本次数据残留 {info.get('residual', '?')}，"
                   f"测试账号 {len(_split_csv(info.get('users')))} 个")
        return True, summary, info
    return False, last, {}


def main() -> int:  # noqa: C901
    cfg = load_config("development")
    password = generate_test_password()
    fault_stage = (os.environ.get(FAULT_ENV, "").strip() or None)

    print("=" * 70)
    print("S2 第四批 · 真实 HTTP 联调（真启动 Flask + 真 MySQL）")
    if fault_stage:
        print(f"※ 故障注入模式：将在阶段 [{fault_stage}] 主动抛出异常（用于异常路径自证）")
    print("=" * 70)

    before, before_err = _non_test_safe(cfg)
    if before is not None:
        print(f"  · 测试前非 tst 数据快照：{_nonzero(before)}", flush=True)

    session = run_session(cfg, password, fault_stage=fault_stage)
    if session["failure"] is not None:
        check("联调过程中无未捕获异常",
              session["injected"] is False,
              f"{type(session['failure']).__name__}: {str(session['failure'])[:80]}")

    print("\n[11] 测试数据清理与残留核验（无论成败均执行）")
    check("Flask 子进程已彻底终止（5000 端口已释放）", session["released"],
          "" if session["released"] else f"仍有进程监听 {PORT}")
    check("cleanup 已在 finally 中执行且未抛异常",
          session["cleanup_failure"] is None and session["snapshot_failure"] is None,
          "" if session["cleanup_failure"] is None and session["snapshot_failure"] is None
          else f"{type(session['cleanup_failure'] or session['snapshot_failure']).__name__}")
    print(f"  · cleanup 明细：{_nonzero(session['removed'])}"
          f"（合计 {sum(session['removed'].values())} 行）", flush=True)

    left, left_err = _residual_safe(cfg, session["usernames"], session["targets"])
    check("本次 tst 联调测试数据残留行数为 0",
          left is not None and left["total"] == 0,
          _nonzero(left) if left is not None else f"读取失败 {type(left_err).__name__}")

    if fault_stage:
        print("\n[12] 异常路径 cleanup 自证 —— 当前进程即注入子进程，跳过（避免递归）")
    else:
        print("\n[12] 异常路径 cleanup 自证（隔离子进程注入异常，不污染数据库）")
        ok, detail, child_info = fault_selftest()
        check("异常中断时 cleanup 仍在 finally 执行（不污染数据库）", ok, detail)

        child_users = _split_csv(child_info.get("users"))
        child_targets = {"user_ids": _split_csv(child_info.get("uids")),
                         "record_ids": _split_csv(child_info.get("rids"))}
        has_child_scope = bool(child_users or child_targets["user_ids"]
                               or child_targets["record_ids"])
        child_left, child_err = _residual_safe(cfg, child_users, child_targets)
        all_tst, all_tst_err = _tst_residual_safe(cfg)
        ok_precise = ((child_left is not None and child_left["total"] == 0)
                      if has_child_scope else None)
        ok_global = (all_tst is not None and all_tst["total"] == 0)
        detail2 = (f"子进程本次数据残留 {_nonzero(child_left)}；"
                   f"全库 tst 残留 {_nonzero(all_tst)}")
        if ok_precise is None:
            detail2 += "（未取到子进程账号信息，精确核验跳过）"
        if child_err is not None:
            detail2 += f"（精确核验读取失败 {type(child_err).__name__}）"
        if all_tst_err is not None:
            detail2 += f"（全库核验读取失败 {type(all_tst_err).__name__}）"
        check("异常路径执行后测试数据残留行数为 0（精确 ID + 全库 tst 双口径）",
              ok_precise is not False and ok_global, detail2)

        if ((child_left is not None and child_left["total"])
                or (all_tst is not None and all_tst["total"])):
            print("  !! 检测到测试数据残留，执行兜底清理（自证结果仍记为 FAIL）", flush=True)
            try:
                cleanup(cfg, child_users)
            except Exception as exc:
                print(f"  !! 兜底清理失败：{type(exc).__name__}: {exc}", flush=True)

    print("\n[13] 非 tst 真实数据完整性（证明未误删正常数据）")
    after, after_err = _non_test_safe(cfg)
    if before is None or after is None:
        check("非 tst 数据行数测试前后一致（未误删正常数据）", False,
              f"快照读取失败 {type(before_err or after_err).__name__}")
    else:
        diff = {k: (before.get(k, 0), after.get(k, 0))
                for k in BUSINESS_TABLES if before.get(k, 0) != after.get(k, 0)}
        check("非 tst 数据行数测试前后一致（未误删正常数据）", not diff,
              "前后一致" if not diff else f"差异(前,后)={diff}")

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    total = len(RESULTS)
    print()
    print("=" * 70)
    print(f"真实 HTTP 联调结果：{passed}/{total} PASS，{total - passed} FAIL")
    print("=" * 70)

    if fault_stage:
        if (session["injected"] and session["cleanup_failure"] is None
                and left is not None and left["total"] == 0):
            print(FAULT_OK_MARKER, flush=True)
        print(f"{FAULT_STATS_PREFIX}ok={passed} total={total} "
              f"removed={sum(session['removed'].values())} "
              f"residual={left['total'] if left is not None else 'n/a'} "
              f"users={','.join(session['usernames'])} "
              f"uids={','.join(str(i) for i in session['targets'].get('user_ids', []))} "
              f"rids={','.join(str(i) for i in session['targets'].get('record_ids', []))}",
              flush=True)

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
