# -*- coding: utf-8 -*-
"""S2 第二批 —— **真实 HTTP 联调**（真启动 Flask + 真 MySQL，端到端闭环）。

用途：不依赖 Flask 测试客户端，用真实 HTTP 请求验证认证闭环：
`注册 → 登录 → 当前用户 → 刷新 → 改密 → 登出`，并核验统一响应壳与
``X-Request-Id`` 一致性。

用法（必须用后端 venv 的 Python）::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch2_http_smoke.py

安全约定：
- **不打印任何 Token / 密码 / 密钥**（只打印状态码、错误码与布尔结论）；
- 测试数据统一前缀 ``tst``，脚本结束**自动清理**；
- 只读 + 自清理，**不修改数据库结构**。
"""
from __future__ import annotations

import json
import os
import secrets
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

BASE = "http://127.0.0.1:5000/api/v1"
HEALTH = f"{BASE}/health"
PREFIX = "tst"
PASSWORD = "abc12345"
PASSWORD2 = "xyz98765"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    return bool(ok)


def request(method: str, url: str, payload=None, token=None):
    """发起真实 HTTP 请求；返回 ``(status, body_dict, headers)``。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
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
    keys_ok = sorted(body.keys())[:4] == ["code", "data", "message", "request_id"] or set(
        ["code", "message", "data", "request_id"]
    ) <= set(body)
    rid = str(body.get("request_id", ""))
    rid_ok = len(rid) == 32 and all(c in "0123456789abcdef" for c in rid)
    head_ok = headers.get("X-Request-Id") == rid
    return (
        status == expect_status
        and body.get("code") == expect_code
        and keys_ok
        and rid_ok
        and head_ok
    )


def cleanup(cfg) -> int:
    """删除本次联调创建的测试数据（前缀 ``tst``）。"""
    conn = pymysql.connect(
        host=cfg["MYSQL_HOST"], port=int(cfg["MYSQL_PORT"]),
        user=cfg["MYSQL_USER"], password=cfg["MYSQL_PASSWORD"],
        charset=cfg["MYSQL_CHARSET"], autocommit=True,
    )
    removed = 0
    try:
        with conn.cursor() as cur:
            cur.execute(f"USE {cfg['MYSQL_DB']}")
            cur.execute("SELECT id FROM user_account WHERE username LIKE %s", (f"{PREFIX}%",))
            ids = [r[0] for r in cur.fetchall()]
            for table in ("user_session", "user_profile"):
                if ids:
                    fmt = ",".join(["%s"] * len(ids))
                    removed += cur.execute(f"DELETE FROM {table} WHERE user_id IN ({fmt})", ids)
            if ids:
                fmt = ",".join(["%s"] * len(ids))
                removed += cur.execute(f"DELETE FROM user_account WHERE id IN ({fmt})", ids)
            removed += cur.execute(
                "DELETE FROM login_failure_state WHERE username LIKE %s", (f"{PREFIX}%",)
            )
    finally:
        conn.close()
    return removed


def main() -> int:
    cfg = load_config("development")
    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8"}

    print("=" * 70)
    print("S2 第二批 · 真实 HTTP 联调（真启动 Flask + 真 MySQL）")
    print("=" * 70)

    proc = subprocess.Popen(
        [sys.executable, "wsgi.py"], cwd=BACKEND, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    username = f"{PREFIX}{secrets.token_hex(3)}"
    try:
        # ── 0 启动等待 ──
        print("\n[0] 服务启动")
        up = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                status, body, _ = request("GET", HEALTH)
                up = status == 200
                if up:
                    break
            except Exception:
                if proc.poll() is not None:
                    break
        if not check("Flask 真实启动并响应 /api/v1/health", up):
            print("  服务未能启动，终止联调")
            return 1

        # ── 1 注册 ──
        print("\n[1] A-01 注册（真实 HTTP POST）")
        status, body, headers = request("POST", f"{BASE}/auth/register", {
            "username": username, "password": PASSWORD,
            "agreement_version": "v1.0", "agreement_accepted": True,
        })
        check("注册 201 + OK + 响应壳四键 + request_id 一致",
              envelope_ok(status, body, headers, 201, "OK"), f"HTTP {status}")
        data = body.get("data") or {}
        tokens = data.get("tokens") or {}
        access, refresh = tokens.get("access_token"), tokens.get("refresh_token")
        check("返回 Token 对且 2h/30d 有效期",
              tokens.get("access_token_expires_in") == 7200
              and tokens.get("refresh_token_expires_in") == 2592000)
        check("响应未回显密码 / 哈希",
              PASSWORD not in json.dumps(body, ensure_ascii=False))

        # ── 2 登录 ──
        print("\n[2] A-02 登录（真实 HTTP POST）")
        status, body, headers = request("POST", f"{BASE}/auth/login",
                                        {"username": username, "password": PASSWORD})
        check("登录 200 + OK", envelope_ok(status, body, headers, 200, "OK"), f"HTTP {status}")
        login_access = ((body.get("data") or {}).get("tokens") or {}).get("access_token")
        check("登录返回 profile_initialized 字段", "profile_initialized" in (body.get("data") or {}))

        status, body, headers = request("POST", f"{BASE}/auth/login",
                                        {"username": username, "password": "wrongpw123"})
        check("错误密码 → 401 CREDENTIALS_INVALID",
              envelope_ok(status, body, headers, 401, "CREDENTIALS_INVALID"), f"HTTP {status}")

        status, body, headers = request("POST", f"{BASE}/auth/login",
                                        {"username": username, "password": PASSWORD, "user_id": 1})
        check("请求体携带 user_id → 400 INVALID_PARAM",
              envelope_ok(status, body, headers, 400, "INVALID_PARAM"), f"HTTP {status}")

        # ── 3 当前用户 ──
        print("\n[3] A-06 当前用户（真实 HTTP GET）")
        status, body, headers = request("GET", f"{BASE}/users/me", token=login_access)
        check("GET /users/me 200 + 返回 username",
              envelope_ok(status, body, headers, 200, "OK")
              and (body.get("data") or {}).get("username") == username, f"HTTP {status}")
        check("不返回 password_hash / role 等敏感字段",
              not ({"password_hash", "password_algo", "role"} & set((body.get("data") or {}).keys())))

        status, body, headers = request("GET", f"{BASE}/users/me")
        check("无 Token → 401 UNAUTHENTICATED",
              envelope_ok(status, body, headers, 401, "UNAUTHENTICATED"), f"HTTP {status}")

        status, body, headers = request("GET", f"{BASE}/users/me?user_id=1", token=login_access)
        check("query 携带 user_id → 400 INVALID_PARAM",
              envelope_ok(status, body, headers, 400, "INVALID_PARAM"), f"HTTP {status}")

        # ── 4 刷新 + 重放 ──
        print("\n[4] A-03 刷新 Token（真实 HTTP POST）")
        status, body, headers = request("POST", f"{BASE}/auth/refresh", {"refresh_token": refresh})
        check("刷新 200 + 返回新 Token 对",
              envelope_ok(status, body, headers, 200, "OK")
              and bool((body.get("data") or {}).get("access_token")), f"HTTP {status}")
        rotated = body.get("data") or {}

        status, body, headers = request("POST", f"{BASE}/auth/refresh", {"refresh_token": refresh})
        check("重放旧刷新令牌 → 401 TOKEN_REUSED",
              envelope_ok(status, body, headers, 401, "TOKEN_REUSED"), f"HTTP {status}")

        status, _, _ = request("GET", f"{BASE}/users/me", token=login_access)
        check("重放后旧会话全部失效 → 401", status == 401, f"HTTP {status}")
        status, _, _ = request("GET", f"{BASE}/users/me", token=rotated.get("access_token"))
        check("重放后新签发会话亦失效 → 401", status == 401, f"HTTP {status}")
        status, _, _ = request("POST", f"{BASE}/auth/refresh",
                               {"refresh_token": rotated.get("refresh_token")})
        check("重放后刷新令牌亦失效 → 401", status == 401, f"HTTP {status}")

        # ── 5 改密 ──
        print("\n[5] A-05 修改密码（真实 HTTP PUT）")
        status, body, headers = request("POST", f"{BASE}/auth/login",
                                        {"username": username, "password": PASSWORD})
        cur = ((body.get("data") or {}).get("tokens") or {}).get("access_token")

        status, body, headers = request("PUT", f"{BASE}/auth/password", {
            "old_password": "badpw1234", "new_password": PASSWORD2, "confirm_password": PASSWORD2},
            token=cur)
        check("原密码错误 → 422 PASSWORD_INVALID",
              envelope_ok(status, body, headers, 422, "PASSWORD_INVALID"), f"HTTP {status}")

        status, body, headers = request("PUT", f"{BASE}/auth/password", {
            "old_password": PASSWORD, "new_password": PASSWORD2,
            "confirm_password": "mismatch1"}, token=cur)
        check("两次输入不一致 → 422 VALIDATION_FAILED",
              envelope_ok(status, body, headers, 422, "VALIDATION_FAILED"), f"HTTP {status}")

        status, body, headers = request("PUT", f"{BASE}/auth/password", {
            "old_password": PASSWORD, "new_password": PASSWORD2,
            "confirm_password": PASSWORD2}, token=cur)
        check("改密成功 200 + all_sessions_revoked=true",
              envelope_ok(status, body, headers, 200, "OK")
              and (body.get("data") or {}).get("all_sessions_revoked") is True, f"HTTP {status}")

        status, _, _ = request("GET", f"{BASE}/users/me", token=cur)
        check("改密后旧 Access Token 失效 → 401", status == 401, f"HTTP {status}")
        status, _, _ = request("POST", f"{BASE}/auth/login",
                               {"username": username, "password": PASSWORD})
        check("改密后旧密码不可登录 → 401", status == 401, f"HTTP {status}")

        # ── 6 登出 ──
        print("\n[6] A-04 退出登录（真实 HTTP POST）")
        status, body, headers = request("POST", f"{BASE}/auth/login",
                                        {"username": username, "password": PASSWORD2})
        t = ((body.get("data") or {}).get("tokens") or {}).get("access_token")
        status, body, headers = request("POST", f"{BASE}/auth/logout", token=t)
        check("登出 200 + data 为 null",
              envelope_ok(status, body, headers, 200, "OK") and body.get("data") is None,
              f"HTTP {status}")
        status, _, _ = request("GET", f"{BASE}/users/me", token=t)
        check("登出后当前会话失效 → 401", status == 401, f"HTTP {status}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # ── 7 清理 ──
    print("\n[7] 测试数据清理")
    removed = cleanup(cfg)
    check(f"已清理联调产生的测试数据（{removed} 行）", True)

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    total = len(RESULTS)
    print()
    print("=" * 70)
    print(f"真实 HTTP 联调结果：{passed}/{total} PASS，{total - passed} FAIL")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
