# -*- coding: utf-8 -*-
"""康迹 HealthTrack —— 数据库登录诊断（**绝不打印明文口令**）

用途：当 `.env.<APP_ENV>` 已配置开发账号但连接报 1045 Access denied 时，
      用本脚本定位到底是「口令值不对」「.env 解析被截断」还是「账号本身不存在/被锁」。

用法（务必用 backend 的 venv Python）：
    backend\\.venv\\Scripts\\python.exe scripts\\diag_db_login.py
    backend\\.venv\\Scripts\\python.exe scripts\\diag_db_login.py --probe-variants
    backend\\.venv\\Scripts\\python.exe scripts\\diag_db_login.py --password-stdin
    backend\\.venv\\Scripts\\python.exe scripts\\diag_db_login.py --admin-user root --show-account --password-stdin

安全说明：
- 只输出「长度 / 字符类别 / 布尔指纹」，**不输出口令本身**，也不写入任何文件。
- 异常信息中的口令由 PyMySQL 屏蔽，无须担心回显。
- `--probe-variants` 会额外尝试「文件原始字面值」与「去掉首尾引号」两种解析变体，
  用于判定是否为 .env 解析artifact（这是解析假设验证，不是暴力枚举口令）。
"""
from __future__ import annotations

import argparse
import getpass
import io
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

ENV_NAME = (os.environ.get("APP_ENV") or "development").strip().lower()
ENV_FILE = BACKEND / f".env.{ENV_NAME}"

SEP = "=" * 68


def say(msg=""):
    print(msg, flush=True)


def fingerprint(value: str) -> dict:
    """给出值的"指纹"——只含长度与字符类别，绝不含明文。"""
    v = "" if value is None else str(value)
    return {
        "长度": len(v),
        "空值": len(v) == 0,
        "含空格/制表符": bool(re.search(r"[ \t]", v)),
        "含 #": "#" in v,
        "含 $": "$" in v,
        "含 %": "%" in v,
        "含 @": "@" in v,
        "含 :": ":" in v,
        "含 /": "/" in v,
        "含 \\": "\\" in v,
        "含 单引号": "'" in v,
        "含 双引号": '"' in v,
        "含 单引号对": v.startswith("'") and v.endswith("'") and len(v) >= 2,
        "含 双引号对": v.startswith('"') and v.endswith('"') and len(v) >= 2,
        "含 非 ASCII": any(ord(c) > 127 for c in v),
        "含 首尾空白": v != v.strip(),
    }


def read_raw_env(path: Path) -> dict:
    """按「字面值」读取 dotenv 文件（不做变量展开、不去注释），用于与 dotenv 结果比对。"""
    out = {}
    if not path.is_file():
        return out
    for line in io.open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--probe-variants", action="store_true",
                    help="额外尝试文件原始字面值/去引号变体（判定 .env 解析 artifact）")
    ap.add_argument("--password-stdin", action="store_true",
                    help="从标准输入读取口令（不回显、不入 shell 历史）")
    ap.add_argument("--admin-user", default=None, help="以管理员账号做账号状态核查")
    ap.add_argument("--show-account", action="store_true",
                    help="列出 mysql.user 中该账号的 host/plugin/锁定状态 + GRANTS")
    args = ap.parse_args()

    say(SEP)
    say("康迹 HealthTrack —— 数据库登录诊断（不打印明文口令）")
    say(SEP)
    say(f"APP_ENV      : {ENV_NAME}")
    say(f"配置文件     : {ENV_FILE}")
    say(f"文件存在     : {ENV_FILE.is_file()}"
        + (f"   ({ENV_FILE.stat().st_size} B)" if ENV_FILE.is_file() else ""))
    say()

    if not ENV_FILE.is_file():
        say("!! 配置文件不存在，无法继续。")
        return 2

    # ── 1) dotenv 解析值 ──
    try:
        from dotenv import dotenv_values
    except Exception as e:
        say(f"!! 无法导入 python-dotenv（请用 backend\\.venv 的 Python 运行）：{e!r}")
        return 2

    parsed = dotenv_values(str(ENV_FILE))
    raw = read_raw_env(ENV_FILE)

    say("── 非敏感配置项 ──")
    for k in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DB", "MYSQL_CHARSET"):
        say(f"  {k:<14} = {parsed.get(k)!r}")

    user = parsed.get("MYSQL_USER")
    pwd = parsed.get("MYSQL_PASSWORD")
    host = parsed.get("MYSQL_HOST") or "127.0.0.1"
    port = int(parsed.get("MYSQL_PORT") or 3306)

    say()
    say("── 口令指纹（不含明文）──")
    fp = fingerprint(pwd)
    for k, v in fp.items():
        say(f"  {k:<14} : {v}")
    if not user or not str(user).strip() or str(user).startswith("CHANGE_ME"):
        say()
        say("!! MYSQL_USER 仍为占位符或为空 —— 请先在配置文件中填写真实开发账号。")
        return 1
    if fp["空值"] or str(pwd or "").startswith("CHANGE_ME"):
        say()
        say("!! MYSQL_PASSWORD 仍为占位符或为空 —— 请先填写真实口令。")
        return 1

    # ── 2) 与文件原始字面值比对（判定解析 artifact）──
    say()
    say("── .env 解析一致性 ──")
    raw_pwd = raw.get("MYSQL_PASSWORD")
    raw_fp = fingerprint(raw_pwd)
    same = (raw_pwd == pwd)
    say(f"  文件字面值长度 : {raw_fp['长度']}")
    say(f"  dotenv 解析长度: {fp['长度']}")
    say(f"  两者是否一致   : {same}")
    if not same:
        say("  ⚠ 不一致！常见原因：值里含 '#'（被当行内注释截断）、'$'（被做变量展开）、")
        say("    或首尾引号/空格被吞。→ 建议给口令加【单引号】包裹，或改用 --password-stdin 验证。")

    # ── 3) 连接测试 ──
    def try_connect(pw_value, label):
        try:
            import pymysql
        except Exception as e:
            say(f"  !! PyMySQL 不可用：{e!r}")
            return None, "NO_PYMYSQL"
        try:
            c = pymysql.connect(host=host, port=port, user=user, password=pw_value,
                                charset=parsed.get("MYSQL_CHARSET") or "utf8mb4",
                                connect_timeout=8)
            return c, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    say()
    say("── 连通性测试 ──")
    conn, err = try_connect(pwd, "parsed")
    if conn:
        say("  PASS  使用 dotenv 解析值连接成功")
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), CURRENT_USER(), DATABASE()")
            v, cu, db = cur.fetchone()
        say(f"        MySQL={v}  认证身份={cu}  当前库={db}")
        conn.close()
    else:
        say(f"  FAIL  使用 dotenv 解析值连接失败：{err}")

    if args.probe_variants and not conn:
        variants = []
        if raw_pwd is not None and raw_pwd != pwd:
            variants.append(("文件原始字面值", raw_pwd))
        for name, val in list(variants):
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                variants.append((name + "（去引号）", val[1:-1]))
        if not variants:
            say("  --probe-variants：无可试变体（解析值与字面值相同且无包裹引号）")
        for name, val in variants:
            c2, e2 = try_connect(val, name)
            say(f"  {'PASS' if c2 else 'FAIL'}  变体[{name}] len={len(val)}"
                + ("" if c2 else f"  {e2}"))
            if c2:
                say("        → 说明问题出在 .env 值写法，请改用该写法（建议单引号包裹）。")
                c2.close()
                break

    if args.password_stdin:
        say()
        say("── 手工口令验证（--password-stdin）──")
        manual = getpass.getpass("请输入 MYSQL_PASSWORD（不回显）：")
        c3, e3 = try_connect(manual, "stdin")
        say(("  PASS  手工输入的口令可登录" if c3 else f"  FAIL  手工输入的口令仍失败：{e3}"))
        if c3:
            say("        → 配置值有误；请把手工输入的同款口令按其字面写入 .env.development。")
            c3.close()
        else:
            say("        → 配置读取无误，问题在 MySQL 侧（账号不存在 / 口令不符 / 主机不匹配）。")

    # ── 4) 管理员视角核查账号 ──
    if args.admin_user:
        say()
        say(f"── 管理员核查（--admin-user {args.admin_user}）──")
        admin_pw = getpass.getpass(f"请输入 {args.admin_user} 的口令（不回显）：")
        try:
            import pymysql
            ac = pymysql.connect(host=host, port=port, user=args.admin_user,
                                 password=admin_pw, charset="utf8mb4", connect_timeout=8)
        except Exception as e:
            say(f"  FAIL  管理员连接失败：{type(e).__name__}: {e}")
        else:
            with ac.cursor() as cur:
                cur.execute("SELECT user, host, plugin, account_locked "
                            "FROM mysql.user WHERE user = %s", (user,))
                rows = cur.fetchall()
            say(f"  mysql.user 中 user={user!r} 的记录数：{len(rows)}")
            for r in rows:
                say(f"    user={r[0]} host={r[1]} plugin={r[2]} locked={r[3]}")
            if not rows:
                say("    ⚠ 该账号**不存在** → 需重新执行 CREATE USER（见 scripts/init_db_dev.sql）")
            if args.show_account and rows:
                for r in rows:
                    try:
                        with ac.cursor() as cur:
                            cur.execute(f"SHOW GRANTS FOR '{r[0]}'@'{r[1]}'")
                            for g in cur.fetchall():
                                say(f"    GRANT: {g[0]}")
                    except Exception as e:
                        say(f"    GRANT 查询失败：{e}")
                with ac.cursor() as cur:
                    cur.execute("SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, "
                                "DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA "
                                "WHERE SCHEMA_NAME = %s", (parsed.get("MYSQL_DB"),))
                    for r in cur.fetchall():
                        say(f"    库 {r[0]}：charset={r[1]} collation={r[2]}")
            ac.close()

    say()
    say(SEP)
    say("诊断结束。若上面显示连接失败但解析一致性为 True，请以管理员执行：")
    say("  SELECT user,host,plugin,account_locked FROM mysql.user WHERE user='kangji_dev';")
    say("  ALTER USER 'kangji_dev'@'localhost' IDENTIFIED BY '<新口令>';")
    say("  FLUSH PRIVILEGES;")
    say(SEP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
