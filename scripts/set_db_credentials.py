# -*- coding: utf-8 -*-
"""康迹 HealthTrack —— 安全对齐数据库凭据 + 一键完成 S2 第一批实机验收

用途：
    配置文件里的 MYSQL_PASSWORD 与 MySQL 账号当前口令不一致时，
    在本机安全地把它改对（**不回显、不入 shell 历史、不写日志、不进报告**）。

安全设计（每一条都重要）：
    1. 口令用 getpass 从终端读取 —— 不回显、不进命令行参数、不进 shell 历史。
    2. **先验证、后落盘**：先用输入值真连一次 MySQL；连不上就不写文件、不改任何东西。
    3. 落盘后立即用 dotenv 重新解析并断言与输入值**完全一致**（防止引号/转义写坏）。
    4. 全程**不打印口令明文**，只打印长度与布尔指纹。
    5. 不创建账号、不修改权限、不改数据库设计、不改 S1 封板文档、不改业务代码。

用法（务必用 backend 的 venv Python）：
    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\set_db_credentials.py
    backend\\.venv\\Scripts\\python.exe scripts\\set_db_credentials.py --accept   # 顺带跑迁移+验收
"""
from __future__ import annotations

import argparse
import getpass
import io
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

SAFE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "_-."
)


def say(msg=""):
    print(msg, flush=True)


def encode_env_value(value: str) -> str:
    """按 python-dotenv 的语义安全编码 .env 值。

    - 仅含 [A-Za-z0-9_-.]: 直接裸写（不会被 # 注释 / $ 展开 / 引号吞掉）
    - 其它情况: 用单引号包裹；python-dotenv 对单引号值仅反转义 \\' 与 \\\\，
      故先把 \\ 转成 \\\\、再把 ' 转成 \\'。
    """
    if value and all(c in SAFE_CHARS for c in value):
        return value
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def fingerprint(value: str) -> str:
    v = "" if value is None else str(value)
    flags = []
    if any(c.isspace() for c in v):
        flags.append("含空白")
    for ch, name in (("#", "#"), ("$", "$"), ("%", "%"), ("@", "@"),
                     (":", ":"), ("/", "/"), ("\\", "反斜杠"),
                     ("'", "单引号"), ('"', "双引号")):
        if ch in v:
            flags.append(name)
    if any(ord(c) > 127 for c in v):
        flags.append("非ASCII")
    return f"长度={len(v)}; " + ("特殊字符: " + ",".join(flags) if flags else "无特殊字符")


def read_env_file(path: Path) -> list[str]:
    with io.open(path, encoding="utf-8", errors="strict") as f:
        return f.read().splitlines()


def test_connection(user, pwd, host, port, db, charset) -> tuple[bool, str]:
    try:
        import pymysql
    except Exception as e:  # pragma: no cover
        return False, f"PyMySQL 不可用: {e!r}"
    try:
        conn = pymysql.connect(host=host, port=int(port), user=user, password=pwd,
                               database=db, charset=charset or "utf8mb4",
                               connect_timeout=8)
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), CURRENT_USER(), DATABASE(), "
                        "@@character_set_database, @@collation_database")
            row = cur.fetchone()
        conn.close()
        return True, (f"MySQL={row[0]}  CURRENT_USER={row[1]}  DB={row[2]}  "
                      f"charset={row[3]}  collation={row[4]}")
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:280]}"


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--env", default=os.environ.get("APP_ENV") or "development",
                    help="目标环境（对应 backend/.env.<env>），默认 development")
    ap.add_argument("--accept", action="store_true",
                    help="凭据对齐成功后，顺带执行 alembic upgrade head + verify_s2_batch1.py --db")
    ap.add_argument("--no-write", action="store_true",
                    help="只验证不落盘（自检用）")
    args = ap.parse_args()

    env_name = args.env.strip().lower()
    env_file = BACKEND / f".env.{env_name}"

    say("=" * 68)
    say("康迹 HealthTrack —— 数据库凭据安全对齐")
    say("=" * 68)
    say(f"目标配置文件 : {env_file}")
    if not env_file.is_file():
        say(f"!! 配置文件不存在，无法继续（请先创建 backend/.env.{env_name}）")
        return 2

    # ── 读出非敏感项 ──
    try:
        from dotenv import dotenv_values
    except Exception as e:
        say(f"!! 无法导入 python-dotenv（请用 backend\\.venv 的 Python 运行）：{e!r}")
        return 2

    cur = dotenv_values(str(env_file))
    user = (cur.get("MYSQL_USER") or "").strip()
    host = (cur.get("MYSQL_HOST") or "127.0.0.1").strip()
    port = (cur.get("MYSQL_PORT") or "3306").strip()
    db = (cur.get("MYSQL_DB") or "kangji_healthtrack").strip()
    charset = (cur.get("MYSQL_CHARSET") or "utf8mb4").strip()

    say(f"MYSQL_USER    : {user}")
    say(f"MYSQL_HOST    : {host}")
    say(f"MYSQL_PORT    : {port}")
    say(f"MYSQL_DB      : {db}")
    say(f"现有口令指纹  : {fingerprint(cur.get('MYSQL_PASSWORD'))}")
    say()

    if not user or "CHANGE_ME" in user.upper():
        say("!! MYSQL_USER 未配置或仍为占位符 —— 请先在配置文件中填好 kangji_dev。")
        return 2

    # ── 交互读取口令（不回显）──
    # Windows 下 getpass 直接读控制台（不读管道/重定向），非交互环境会阻塞，
    # 故先做守卫：必须在真实终端中运行。
    if not sys.stdin.isatty():
        say("!! 当前不是交互式终端（stdin 非 TTY），无法安全读取口令。")
        say("   请在**你自己的 CMD / PowerShell 窗口**里直接运行本脚本：")
        say("       cd C:\\Users\\Toporder-WS\\Desktop\\Demo")
        say("       backend\\.venv\\Scripts\\python.exe scripts\\set_db_credentials.py --accept")
        say("   不要用管道、重定向或自动化方式调用。已退出，未改动任何文件。")
        return 2

    say("请在下方输入 MySQL 账号的【当前真实口令】。")
    say(f"（账号：{user}@{host}:{port}；输入不会显示、不会进 shell 历史、不会写入报告）")
    say()
    try:
        pwd1 = getpass.getpass("  口令: ")
        pwd2 = getpass.getpass("  再输一次确认: ")
    except (KeyboardInterrupt, EOFError):
        say("\n已取消。")
        return 130

    if pwd1 != pwd2:
        say("!! 两次输入不一致，已取消（未改动任何文件）。")
        return 1
    if not pwd1 or "CHANGE_ME" in pwd1.upper():
        say("!! 口令为空或仍是占位符，已取消（未改动任何文件）。")
        return 1

    say(f"\n已读取口令指纹 : {fingerprint(pwd1)}")
    say("正在验证……")

    # ── 先验证，后落盘 ──
    ok, info = test_connection(user, pwd1, host, port, db, charset)
    if not ok:
        say(f"  FAIL  该口令无法登录：{info}")
        say()
        say("已取消 —— **未修改任何文件**。请确认：")
        say("  1) 口令是否为 kangji_dev@localhost 的当前口令（注意大小写与首尾空格）")
        say("  2) 该账号是否确实拥有 kangji_healthtrack 的访问权限")
        return 1
    say(f"  PASS  验证通过：{info}")

    if args.no_write:
        say("\n--no-write：仅验证，不落盘。")
        return 0

    # ── 落盘（只替换 MYSQL_PASSWORD 行，其余原样保留）──
    lines = read_env_file(env_file)
    encoded = encode_env_value(pwd1)
    replaced = False
    new_lines = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("MYSQL_PASSWORD") and "=" in stripped and not stripped.startswith("#"):
            new_lines.append(f"MYSQL_PASSWORD={encoded}")
            replaced = True
        else:
            new_lines.append(ln)
    if not replaced:
        new_lines.append(f"MYSQL_PASSWORD={encoded}")

    tmp = env_file.with_suffix(env_file.suffix + ".tmp")
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(new_lines) + "\n")
    os.replace(tmp, env_file)
    say(f"  PASS  已写入 {env_file.name}（MYSQL_PASSWORD 行{'替换' if replaced else '新增'}；"
        f"编码方式={'裸值' if encoded == pwd1 else '单引号包裹'}）")

    # ── 回读断言 ──
    reread = dotenv_values(str(env_file))
    if reread.get("MYSQL_PASSWORD") != pwd1:
        say("  !!! 回读断言失败：写入值与读取值不一致（引号/转义问题）")
        say("      请把该行改为单引号包裹后重试；本次未做其它修改。")
        return 1
    say("  PASS  回读断言通过（写入值与实际解析值完全一致）")

    # ── 复测（走配置文件，不传内存值）──
    ok2, info2 = test_connection(user, reread.get("MYSQL_PASSWORD"), host, port, db, charset)
    say(f"  {'PASS' if ok2 else 'FAIL'}  经配置文件复测：{info2}")
    if not ok2:
        return 1

    if not args.accept:
        say()
        say("凭据已对齐。下一步（或直接加 --accept 一次跑完）：")
        say("  cd backend && .\\.venv\\Scripts\\python.exe -m alembic upgrade head")
        say("  backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch1.py --db")
        return 0

    # ── 顺带完成验收 ──
    say()
    say("=" * 68)
    say("执行 Alembic 迁移")
    say("=" * 68)
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=str(BACKEND), capture_output=True)
    out = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    say(out if out else "(无输出)")
    say(f"  alembic exit code = {r.returncode}")

    say()
    say("=" * 68)
    say("执行 S2 第一批完整实机验收")
    say("=" * 68)
    r2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_s2_batch1.py"), "--db"],
                        cwd=str(ROOT), capture_output=True)
    out2 = (r2.stdout + r2.stderr).decode("utf-8", "replace")
    say(out2.strip())
    say()
    say("=" * 68)
    say(f"验收脚本 exit code = {r2.returncode}（0 = 全部通过）")
    say("=" * 68)
    return r2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
