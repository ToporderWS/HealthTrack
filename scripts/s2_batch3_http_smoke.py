# -*- coding: utf-8 -*-
"""S2 第三批 —— **真实 HTTP 联调**（真启动 Flask + 真 MySQL，端到端闭环）。

用途：不依赖 Flask 测试客户端，用真实 HTTP 请求验证 P / R 闭环：
``注册 → 档案读写 → 录入 → 查询/详情 → 编辑 → 删除 → 批量删除 → 跨用户隔离``，
并核验统一响应壳、``X-Request-Id`` 一致性、软提示契约与幂等键。

用法（必须用后端 venv 的 Python）::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch3_http_smoke.py

安全约定：
- **不打印任何 Token / 密码 / SECRET_KEY / DB 口令 / Authorization 头**；
- 测试密码**运行时随机生成**（符合现有密码策略），仅存活于当前进程内存，
  **不打印、不落盘、不写入任何配置**；注册与登录复用同一个随机密码；
- 测试账号统一前缀 ``tst`` 且**每次运行随机唯一**。

清理与残留语义（本脚本的硬约束）：
1. ``cleanup()`` 与 Flask 子进程终止**都在 ``finally`` 中执行**；
2. ``cleanup()`` 只删除**本次运行创建**的测试账号（按本次生成的唯一用户名精确定位），
   覆盖该账号的**全部关联数据**；**不使用 TRUNCATE、不删整表、不碰非本次数据**；
3. ``residual()`` 的语义是「**本次 tst 联调测试数据残留行数**」——
   **不是**「整库必须为空」，因此数据库里原本存在的正常业务数据不会导致误 FAIL；
4. ``cleanup()`` 自身失败**不会吞掉**原始测试异常（两者分别记录、分别打印）；
5. 最终 residual check **一定会执行**：``cleanup`` 失败 / residual 读取失败 / residual > 0
   ⇒ 最终结果 FAIL；**绝不因「cleanup 删了 0 行」或「cleanup 没抛异常」就判 PASS**，
   数据是否清理干净**只由 ``residual()`` 判定**；
6. 记录测试前后的**非 tst（真实业务）数据行数快照**并比对，证明未误删正常数据；
7. 额外启动一个**注入故障的隔离子进程**自证「异常路径仍完成清理」，子进程同样自清理。

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pymysql  # noqa: E402

from app.core.config import load_config  # noqa: E402
from app.core.security import check_password_rule  # noqa: E402

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
#: 注入点：R-01 完成之后（此时账号 / 会话 / 档案 / 记录 / 标签均已有测试数据）
FAULT_STAGE = "r01"
#: 子进程「异常后仍完成 cleanup」的证据标记
FAULT_OK_MARKER = "SMOKE_FAULT_CLEANUP_OK"
#: 子进程结果统计行前缀
FAULT_STATS_PREFIX = "SMOKE_FAULT_STATS "
#: 注入的异常特征串
FAULT_TAG = "SMOKE_FAULT_INJECTED"

#: 随机测试密码字符集（字母 + 数字，满足「必须同时含字母与数字」）
_PWD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

RESULTS: list[tuple[str, bool, str]] = []


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
    """运行时生成一个符合**现有密码策略**的随机测试密码。

    策略来源 ``app.core.security.check_password_rule``（8–64 位、必须含字母与数字、
    不得含空格、不得与用户名相同）—— 本函数**不修改**该策略，仅调用它自校验。

    返回值只用于本次 HTTP 联调，**不打印、不写入文件、不写入任何配置**。
    """
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


# ── 数据库：连接 / 定位 / 清理 / 残留 / 非测试数据快照 ────────────────
def _connect(cfg):
    return pymysql.connect(
        host=cfg["MYSQL_HOST"], port=int(cfg["MYSQL_PORT"]),
        user=cfg["MYSQL_USER"], password=cfg["MYSQL_PASSWORD"],
        database=cfg["MYSQL_DB"], charset=cfg["MYSQL_CHARSET"], autocommit=True,
    )


def _ph(n: int) -> str:
    """生成 ``%s,%s,...`` 占位符串。"""
    return ",".join(["%s"] * n)


def _new_counts() -> dict:
    return {t: 0 for t in BUSINESS_TABLES}


def collect_targets(cfg, usernames) -> dict:
    """按**本次运行生成的唯一用户名**定位其 ``user_id`` 与 ``health_record.id``。

    这两个 ID 快照必须在 ``cleanup()`` **之前**采集：即使 ``user_account`` 行已被删除，
    也能据此发现留在子表里的孤儿行（本库无外键、无 CASCADE）。
    """
    targets = {"user_ids": [], "record_ids": []}
    names = [u for u in (usernames or []) if u]
    if not names:
        return targets
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM user_account WHERE username IN ({_ph(len(names))})", names)
            ids = [int(r[0]) for r in cur.fetchall()]
            if ids:
                cur.execute(f"SELECT id FROM health_record WHERE user_id IN ({_ph(len(ids))})", ids)
                targets["record_ids"] = [int(r[0]) for r in cur.fetchall()]
            targets["user_ids"] = ids
    finally:
        conn.close()
    return targets


def cleanup(cfg, usernames) -> dict:
    """删除**本次联调创建**的测试账号及其全部关联数据；返回各表删除行数。

    - 范围：仅本次运行随机生成的唯一用户名（**不使用 ``LIKE 'tst%'`` 作为删除范围**），
      因此不会误删历史遗留的 ``tst`` 数据，也不会触碰任何真实业务数据；
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
            rec_ids: list[int] = []
            if ids:
                ph_ids = _ph(len(ids))
                cur.execute(f"SELECT id FROM health_record WHERE user_id IN ({ph_ids})", ids)
                rec_ids = [int(r[0]) for r in cur.fetchall()]
                # 子表（含 record_tag 的孤儿兜底）→ 主表
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
    """**本次 tst 联调测试数据残留行数**（只统计本次运行创建的数据）。

    与「整库必须为空」有本质区别：数据库里原本存在的正常业务数据**不参与**统计，
    因此不会因为库中有真实用户/档案/记录而误判 FAIL。

    统计口径（全部锚定本次运行的用户名 / ID 快照）：
    - ``user_account`` / ``login_failure_state``：按本次用户名；
    - ``user_profile`` / ``health_record`` / ``health_goal`` / ``user_session`` /
      ``export_job``：按本次 ``user_id`` 快照（账号行已删也能发现子表孤儿行）；
    - ``record_tag``：按本次 ``user_id`` 快照 **或** 本次 ``record_id`` 快照。
    """
    targets = targets or {}
    snap_ids = [int(i) for i in (targets.get("user_ids") or [])]
    snap_recs = [int(i) for i in (targets.get("record_ids") or [])]
    names = [u for u in (usernames or []) if u]

    counts = _new_counts()
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            live_ids: list[int] = []
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
    """全库 ``tst`` 前缀残留（含**历史遗留**）—— 本次精确核验之外的补充安全网。

    已知边界：若某 ``tst`` 账号行已被删除而子表残留孤儿行，本函数无法据前缀反查其
    ``user_id``；该场景由 ``residual()`` 的 ID 快照口径覆盖（会话内精确核验）。
    """
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


def _residual_safe(cfg, usernames, targets=None) -> tuple[dict | None, Exception | None]:
    """``residual()`` 的安全包装：读取失败返回异常（调用方必须判 FAIL）。"""
    try:
        return residual(cfg, usernames, targets), None
    except Exception as exc:
        print(f"  !! residual 读取失败：{type(exc).__name__}: {exc}", flush=True)
        return None, exc


def _tst_residual_safe(cfg) -> tuple[dict | None, Exception | None]:
    try:
        return tst_residual(cfg), None
    except Exception as exc:
        print(f"  !! 全库 tst 残留读取失败：{type(exc).__name__}: {exc}", flush=True)
        return None, exc


def _non_test_safe(cfg) -> tuple[dict | None, Exception | None]:
    try:
        return non_test_counts(cfg), None
    except Exception as exc:
        print(f"  !! 非测试数据快照读取失败：{type(exc).__name__}: {exc}", flush=True)
        return None, exc


def _nonzero(counts: dict | None) -> str:
    """把计数字典渲染成「仅非零项」的短串（``None`` → ``n/a``）。"""
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
    """等待本次启动的 Flask 就绪；``proc`` 为 None（未启动）时安全返回 False。"""
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


def _terminate(proc) -> Exception | None:
    """终止**本次启动的** Flask 子进程及其 reloader 派生的全部子进程。

    ``app.run(debug=True)``（development 默认）会启用 Werkzeug reloader，
    单纯 ``proc.terminate()`` 只结束外层父进程，真正的服务子进程会继续占用 5000 端口；
    因此在 Windows 上使用 ``taskkill /F /T`` 终止整棵进程树。

    **只作用于本脚本 ``Popen`` 得到的 PID**，不会影响任何非本次启动的进程；
    ``proc`` 为 ``None``（启动前失败 / 端口被占用）时直接返回。
    返回异常对象（``None`` 表示成功）—— 调用方负责记录。
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


# ── 用例主体（步骤 1–9；不含启动与清理）──────────────────────────────
def _fault_gate(stage: str, fault_stage: str | None) -> None:
    """故障注入闸门：仅当显式指定 ``fault_stage`` 等于当前阶段时抛异常。"""
    if fault_stage and stage == fault_stage:
        raise InjectedFault(f"{FAULT_TAG}@{stage}")


def run_cases(password: str, fault_stage: str | None = None, created: list | None = None) -> None:  # noqa: C901,E501
    """执行全部真实 HTTP 用例（服务需已就绪）。密码仅在内存中传递。

    ``created`` 会**最先**登记本次生成的测试用户名（即使后续注册/断言失败也能被清理）。
    """
    users = created if created is not None else []
    user = f"{PREFIX}a{secrets.token_hex(3)}"
    peer = f"{PREFIX}b{secrets.token_hex(3)}"
    users.extend([user, peer])
    wrong_password = generate_test_password()

    token = register_and_login(user, password)
    peer_token = register_and_login(peer, password)

    # ── 1 P-01 ──
    print("\n[1] P-01 读取档案（真实 HTTP GET）")
    status, body, headers = request("GET", f"{BASE}/profile", token=token)
    profile = (body.get("data") or {}).get("profile") or {}
    check("P-01 200 + OK + 响应壳",
          envelope_ok(status, body, headers, 200, "OK"), f"HTTP {status}")
    check("未初始化档案 → 全 null 对象（**不是 404**）",
          profile and all(v is None for v in profile.values()))
    check("target_weight 仅返回取数指引（D-1：唯一源 health_goal）",
          (body.get("data") or {}).get("target_weight", {}).get("from") == "health_goal")
    check("derived 结构存在且未产生医学结论",
          "bmi" in ((body.get("data") or {}).get("derived") or {}))

    # ── 2 P-02 ──
    print("\n[2] P-02 更新档案（真实 HTTP PUT）")
    status, body, headers = request("PUT", f"{BASE}/profile", {
        "nickname": "联调用户", "gender": 1, "birth_date": "1995-03-18",
        "height_cm": 175.0, "initial_weight_kg": 72.5, "blood_type": "O",
        "medical_history": "自述文本（仅存储）",
    }, token=token)
    check("P-02 200 + OK（区间内直写，无 warnings）",
          envelope_ok(status, body, headers, 200, "OK")
          and (body.get("data") or {}).get("warnings") == [], f"HTTP {status}")

    status, body, headers = request("GET", f"{BASE}/profile", token=token)
    data = body.get("data") or {}
    check("回读一致 + age 服务端由 birth_date 计算",
          (data.get("profile") or {}).get("nickname") == "联调用户"
          and isinstance((data.get("profile") or {}).get("age"), int))
    check("文本字段按原文回显（不做解读）",
          (data.get("profile") or {}).get("medical_history") == "自述文本（仅存储）")

    status, body, headers = request("PUT", f"{BASE}/profile",
                                    {"height_cm": 300.0}, token=token)
    check("P-02 软提示 → HTTP 200 SOFT_WARNING（本次不写入）",
          envelope_ok(status, body, headers, 200, "SOFT_WARNING")
          and (body.get("data") or {}).get("requires_confirm") is True, f"HTTP {status}")
    check("软提示响应**不带** errors[]（独立 warnings[] 体系）",
          "errors" not in body and (body.get("data") or {}).get("warnings"))
    status, body, _ = request("GET", f"{BASE}/profile", token=token)
    check("软提示未写入（身高仍为 175）",
          (body.get("data") or {}).get("profile", {}).get("height_cm") == 175.0)

    status, body, headers = request("PUT", f"{BASE}/profile",
                                    {"height_cm": 300.0, "acknowledge_warnings": True},
                                    token=token)
    check("确认后重发 → 200 OK 并写入",
          envelope_ok(status, body, headers, 200, "OK"), f"HTTP {status}")
    status, body, _ = request("PUT", f"{BASE}/profile", {"target_weight": 65.0}, token=token)
    check("P-02 拒绝 target_weight → 422（D-1 防双数据源）",
          body.get("code") == "VALIDATION_FAILED", f"HTTP {status}")
    status, body, _ = request("PUT", f"{BASE}/profile", {"user_id": 1}, token=token)
    check("P-02 携带 user_id → 400 INVALID_PARAM",
          body.get("code") == "INVALID_PARAM", f"HTTP {status}")
    # 复原身高，便于后续 BMI 派生
    request("PUT", f"{BASE}/profile", {"height_cm": 175.0}, token=token)

    # ── 3 R-08 ──
    print("\n[3] R-08 录入选项（真实 HTTP GET）")
    status, body, headers = request("GET", f"{BASE}/records/options", token=token)
    opts = body.get("data") or {}
    check("R-08 200 + 8 类指标 + 6 组枚举 + 快捷饮水",
          envelope_ok(status, body, headers, 200, "OK")
          and len(opts.get("metric_types") or []) == 8
          and len(opts.get("enums") or {}) == 6
          and opts.get("water_quick_add") == [200, 250, 500], f"HTTP {status}")
    check("R-08 无医学评价性文案",
          not any(w in json.dumps(opts, ensure_ascii=False)
                  for w in ("建议", "诊断", "正常范围", "偏高", "偏低")))

    # ── 4 R-01 ──
    print("\n[4] R-01 新增记录（真实 HTTP POST）")
    status, body, headers = request("POST", f"{BASE}/records", {
        "metric_type": "weight", "value_1": 70.0, "recorded_at": "2026-09-13 07:30:00",
    }, token=token)
    record = (body.get("data") or {}).get("record") or {}
    check("R-01 201 + OK + 单位由服务端填充",
          envelope_ok(status, body, headers, 201, "OK")
          and record.get("unit") == "kg", f"HTTP {status}")
    check("weight 派生 BMI（不落库）",
          (body.get("data") or {}).get("derived", {}).get("bmi") == 22.9)
    rid = record.get("id")

    status, body, headers = request("POST", f"{BASE}/records", {
        "metric_type": "mood", "value_1": 4, "tags": ["relaxed", "focused"],
        "recorded_at": "2026-09-13 21:00:00",
    }, token=token)
    check("R-01 mood 标签去重保序",
          envelope_ok(status, body, headers, 201, "OK")
          and (body.get("data") or {}).get("record", {}).get("tags") == ["relaxed", "focused"],
          f"HTTP {status}")

    # ★ 故障注入点（仅自证用；正常联调下 fault_stage 为 None，此处为空操作）
    _fault_gate("r01", fault_stage)

    status, body, headers = request("POST", f"{BASE}/records", {
        "metric_type": "weight", "value_1": 70.0, "recorded_at": "2026-09-13 07:30:00",
    }, token=token, extra_headers={"Idempotency-Key": "smoke-idem-0001"})
    first_id = ((body.get("data") or {}).get("record") or {}).get("id")
    status2, body2, headers2 = request("POST", f"{BASE}/records", {
        "metric_type": "weight", "value_1": 70.0, "recorded_at": "2026-09-13 07:30:00",
    }, token=token, extra_headers={"Idempotency-Key": "smoke-idem-0001"})
    check("Idempotency-Key 重放 → 同一条记录（不重复写入）",
          first_id is not None
          and ((body2.get("data") or {}).get("record") or {}).get("id") == first_id
          and body.get("request_id") != body2.get("request_id"))

    status, body, _ = request("POST", f"{BASE}/records", {
        "metric_type": "weight", "value_1": 5000, "recorded_at": "2026-09-13 07:30:00",
    }, token=token)
    check("R-01 不可能值 → 422 硬拦截",
          status == 422 and body.get("code") == "VALIDATION_FAILED", f"HTTP {status}")

    status, body, _ = request("POST", f"{BASE}/records", {
        "metric_type": "weight", "value_1": 320, "recorded_at": "2026-09-13 08:30:00",
    }, token=token)
    check("R-01 疑似录入错误 → 200 SOFT_WARNING（不写入）",
          status == 200 and body.get("code") == "SOFT_WARNING", f"HTTP {status}")
    status, body, _ = request("GET", f"{BASE}/records/count", token=token)
    check("软提示未写入（count 不变）",
          (body.get("data") or {}).get("count") == 3, str((body.get("data") or {}).get("count")))

    # ── 5 R-02 / R-07 ──
    print("\n[5] R-02 列表 / R-07 计数（真实 HTTP GET）")
    status, body, headers = request("GET", f"{BASE}/records", token=token)
    page = body.get("data") or {}
    check("R-02 200 + items/next_cursor/has_more 且**不返回 total**",
          envelope_ok(status, body, headers, 200, "OK")
          and set(page.keys()) == {"items", "next_cursor", "has_more"}, f"HTTP {status}")
    times = [it["recorded_at"] for it in page.get("items") or []]
    check("R-02 排序 recorded_at DESC", times == sorted(times, reverse=True))
    status, body, _ = request("GET", f"{BASE}/records?limit=30", token=token)
    check("R-02 非法 limit → 400 INVALID_PARAM",
          status == 400 and body.get("code") == "INVALID_PARAM", f"HTTP {status}")
    status, body, _ = request("GET", f"{BASE}/records?cursor=not-a-cursor", token=token)
    check("R-02 非法 cursor → 400（不回退为从头发）",
          status == 400 and body.get("code") == "INVALID_PARAM", f"HTTP {status}")
    status, body, headers = request("GET", f"{BASE}/records/count", token=token)
    check("R-07 200 + 返回 count",
          envelope_ok(status, body, headers, 200, "OK")
          and (body.get("data") or {}).get("count") == 3, f"HTTP {status}")

    # ── 6 R-03 / R-04 / R-05 ──
    print("\n[6] R-03 详情 / R-04 编辑 / R-05 删除")
    status, body, headers = request("GET", f"{BASE}/records/{rid}", token=token)
    check("R-03 200 + record + derived",
          envelope_ok(status, body, headers, 200, "OK")
          and set((body.get("data") or {}).keys()) == {"record", "derived"}, f"HTTP {status}")
    status, body, _ = request("GET", f"{BASE}/records/99999999", token=token)
    check("R-03 不存在 → 404 RESOURCE_NOT_FOUND",
          status == 404 and body.get("code") == "RESOURCE_NOT_FOUND", f"HTTP {status}")

    status, body, headers = request("PATCH", f"{BASE}/records/{rid}",
                                    {"value_1": 71.0, "note": "联调备注"}, token=token)
    check("R-04 局部更新 200 + 未改动字段保持",
          envelope_ok(status, body, headers, 200, "OK")
          and (body.get("data") or {}).get("record", {}).get("value_1") == 71.0
          and (body.get("data") or {}).get("record", {}).get("recorded_at")
          == "2026-09-13 07:30:00", f"HTTP {status}")
    status, body, _ = request("PATCH", f"{BASE}/records/{rid}",
                              {"metric_type": "bp"}, token=token)
    check("R-04 修改 metric_type → 422（即使用同值）",
          status == 422 and body.get("code") == "VALIDATION_FAILED", f"HTTP {status}")

    status, body, headers = request("DELETE", f"{BASE}/records/{rid}", token=token)
    check("R-05 软删 200 + deleted_count=1",
          envelope_ok(status, body, headers, 200, "OK")
          and (body.get("data") or {}).get("deleted_count") == 1, f"HTTP {status}")
    status, _, _ = request("GET", f"{BASE}/records/{rid}", token=token)
    check("R-05 软删后详情不可见 → 404", status == 404, f"HTTP {status}")

    # ── 7 R-06 ──
    print("\n[7] R-06 批量删除（真实 HTTP POST）")
    status, body, _ = request("POST", f"{BASE}/records/batch-delete",
                              {"metric_type": "mood", "password": wrong_password}, token=token)
    check("密码错误 → 422 PASSWORD_INVALID",
          status == 422 and body.get("code") == "PASSWORD_INVALID", f"HTTP {status}")
    status, body, _ = request("POST", f"{BASE}/records/batch-delete",
                              {"metric_type": "mood", "password": password,
                               "expected_count": 99}, token=token)
    check("expected_count 不一致 → 409 COUNT_MISMATCH",
          status == 409 and body.get("code") == "COUNT_MISMATCH", f"HTTP {status}")
    status, body, headers = request("POST", f"{BASE}/records/batch-delete",
                                    {"metric_type": "mood", "password": password}, token=token)
    check("批量删除成功 200 + deleted_count=1",
          envelope_ok(status, body, headers, 200, "OK")
          and (body.get("data") or {}).get("deleted_count") == 1, f"HTTP {status}")

    # ── 8 跨用户隔离 ──
    print("\n[8] 跨用户隔离（真实 HTTP）")
    status, body, _ = request("POST", f"{BASE}/records", {
        "metric_type": "water", "value_1": 250, "recorded_at": "2026-09-13 09:00:00",
    }, token=peer_token)
    peer_rid = ((body.get("data") or {}).get("record") or {}).get("id")
    status, _b, _h = request("GET", f"{BASE}/records/{peer_rid}", token=token)
    check("跨用户读取详情 → 统一 404", status == 404, f"HTTP {status}")
    status, _b, _h = request("PATCH", f"{BASE}/records/{peer_rid}", {"value_1": 1}, token=token)
    check("跨用户编辑 → 统一 404", status == 404, f"HTTP {status}")
    status, _b, _h = request("DELETE", f"{BASE}/records/{peer_rid}", token=token)
    check("跨用户删除 → 统一 404", status == 404, f"HTTP {status}")
    status, body, _ = request("GET", f"{BASE}/records/count", token=token)
    check("本人 count 不受他人数据影响",
          (body.get("data") or {}).get("count") == 1, str((body.get("data") or {}).get("count")))
    status, body, _ = request("GET", f"{BASE}/records/count", token=peer_token)
    check("他人 count 亦不受影响（数据未被误删）",
          (body.get("data") or {}).get("count") == 1, str((body.get("data") or {}).get("count")))

    # ── 9 未认证 ──
    print("\n[9] 认证守卫（真实 HTTP）")
    unauth = 0
    for method, path, payload in (
        ("GET", "/profile", None), ("PUT", "/profile", {}),
        ("POST", "/records", {}), ("GET", "/records", None),
        ("GET", "/records/count", None), ("GET", "/records/options", None),
        ("POST", "/records/batch-delete", {}), ("GET", "/records/1", None),
        ("PATCH", "/records/1", {}), ("DELETE", "/records/1", None),
    ):
        st, _b, _h = request(method, f"{BASE}{path}", payload)
        if st == 401:
            unauth += 1
    check("P / R 全部接口免 Token → 401", unauth == 10, f"{unauth}/10")


# ── 一次完整会话（启动 → 用例 → finally：终止 + 清理）────────────────
def run_session(cfg, password: str, fault_stage: str | None = None) -> dict:
    """启动 Flask、执行用例，并**在 finally 中**终止子进程与清理测试数据。

    无论正常完成、断言失败、HTTP 异常、服务启动失败、端口被占用，还是注入异常，
    ``_terminate()`` 与 ``cleanup()`` 都会被尝试执行；两者各自的异常分别记录，
    互不吞并，也不吞掉原始测试异常。
    """
    global RESULTS
    saved = RESULTS
    RESULTS = []

    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8"}
    created: list[str] = []
    proc = None
    failure = None
    proc_failure = None
    cleanup_failure = None
    snapshot_failure = None
    targets: dict = {"user_ids": [], "record_ids": []}
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
            # 子进程输出必须**丢弃**：本脚本请求数较多，若用 PIPE 且不读取，
            # 日志会写满管道缓冲区导致服务端阻塞、后续请求超时。
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not _wait_server_up(proc):
            check("Flask 真实启动并响应 /api/v1/health", False, "超时未就绪")
            raise RuntimeError("Flask 服务未能在超时内启动，联调终止")
        check("Flask 真实启动并响应 /api/v1/health", True)
        run_cases(password, fault_stage, created)
    except Exception as exc:
        failure = exc
        injected = isinstance(exc, InjectedFault)
        print(f"\n  !! 联调中断：{type(exc).__name__}: {str(exc)[:120]}", flush=True)
    finally:
        # (2) Flask 子进程终止（含 reloader 派生的子进程）—— 必须执行
        proc_failure = _terminate(proc)
        if proc_failure is not None:
            print(f"  !! Flask 子进程终止异常：{type(proc_failure).__name__}: {proc_failure}",
                  flush=True)
        released = _wait_port_released()
        # 清理前采集本次测试账号的 ID 快照（账号行删除后仍可发现子表孤儿行）
        try:
            targets = collect_targets(cfg, created)
        except Exception as exc:
            snapshot_failure = exc
            print(f"  !! 测试账号 ID 快照失败：{type(exc).__name__}: {exc}", flush=True)
        # (1) 测试数据清理 —— 必须执行；其失败不得吞掉上面的原始异常
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
    # 本次会话的断言必须并回主统计（否则会话内的用例会被漏计）
    saved.extend(RESULTS)
    RESULTS = saved
    return session


# ── 异常路径自证（隔离子进程注入故障）────────────────────────────────
def _parse_stats(out: str) -> dict:
    """解析子进程的 ``SMOKE_FAULT_STATS`` 行（``key=value`` 空格分隔）。"""
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


def fault_selftest(attempts: int = 2) -> tuple[bool, str, dict]:
    """在**独立子进程**中注入异常，自证「异常路径下 cleanup 仍在 finally 执行」。

    - 子进程使用独立的随机密码与独立随机 ``tst`` 账号，且自身也执行 finally 清理，
      因此**不会污染数据库**；
    - 子进程检测到 ``SMOKE_INJECT_FAULT_STAGE`` 后只做一次注入，**不会再次调用本函数**
      （见 ``main`` 的 ``fault_stage`` 分支），**不存在递归**；
    - 返回 ``(是否通过, 说明, 子进程自报统计)``，父进程据此再做独立残留核验。
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
    # 运行时随机测试密码：仅在内存中传递，不打印、不落盘、不写入配置
    password = generate_test_password()
    fault_stage = (os.environ.get(FAULT_ENV, "").strip() or None)

    print("=" * 70)
    print("S2 第三批 · 真实 HTTP 联调（真启动 Flask + 真 MySQL）")
    if fault_stage:
        print(f"※ 故障注入模式：将在阶段 [{fault_stage}] 主动抛出异常（用于异常路径自证）")
    print("=" * 70)

    # 测试前：非 tst（真实业务）数据行数快照
    before, before_err = _non_test_safe(cfg)
    if before is not None:
        print(f"  · 测试前非 tst 数据快照：{_nonzero(before)}", flush=True)

    # ── 正常路径：启动 → 用例 → finally（终止 + 清理）──
    session = run_session(cfg, password, fault_stage=fault_stage)
    if session["failure"] is not None:
        check("联调过程中无未捕获异常",
              session["injected"] is False,
              f"{type(session['failure']).__name__}: {str(session['failure'])[:80]}")

    # ── 10 清理与「本次测试数据」残留核验（无论成败均执行）──
    print("\n[10] 测试数据清理与残留核验（无论成败均执行）")
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

    # ── 11 异常路径自证（仅父进程执行，避免递归）──
    if fault_stage:
        print("\n[11] 异常路径 cleanup 自证 —— 当前进程即注入子进程，跳过（避免递归）")
    else:
        print("\n[11] 异常路径 cleanup 自证（隔离子进程注入异常，不污染数据库）")
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

        # 兜底：若确有残留，先确保数据库恢复干净（自证结论已按 FAIL 记录，不做掩盖）
        if ((child_left is not None and child_left["total"])
                or (all_tst is not None and all_tst["total"])):
            print("  !! 检测到测试数据残留，执行兜底清理（自证结果仍记为 FAIL）", flush=True)
            try:
                cleanup(cfg, child_users)
            except Exception as exc:
                print(f"  !! 兜底清理失败：{type(exc).__name__}: {exc}", flush=True)

    # ── 12 非 tst（真实业务）数据未被误删 ──
    print("\n[12] 非 tst 真实数据完整性（证明未误删正常数据）")
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
        # 仅当「异常确已注入 + finally 完成清理 + 本次数据无残留」时输出证据标记
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
