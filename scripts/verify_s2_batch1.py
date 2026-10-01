# -*- coding: utf-8 -*-
"""
康迹 HealthTrack —— S2 第一批 骨架核验脚本
==========================================

用途：一键核验 S2 第一批交付物是否仍然完好，并可（在填好数据库凭据后）
      执行数据库只读核验。

运行方式（在项目根目录 Demo/ 下执行）：

    # 1) 不连库部分（随时可跑，不需要数据库）
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch1.py

    # 2) 追加数据库只读核验（需先在 backend\\.env.development 填好
    #    MYSQL_USER / MYSQL_PASSWORD）
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch1.py --db

参数：
    --db     追加执行数据库只读核验（A~L 项）
    --quiet  只输出失败项与总结

安全说明：
    - 本脚本**只读**，不创建 / 修改 / 删除任何数据库对象与文件。
    - 不打印任何密码、令牌等敏感值。
    - 退出码：0 = 全部通过；1 = 存在失败项。
"""

import argparse
import json
import os
import re
import sys
import time
import subprocess
import urllib.error
import urllib.request

# ---------------------------------------------------------------- 路径与常量

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")
VENV_PY = os.path.join(BACKEND, ".venv", "Scripts", "python.exe")
SCHEMA_SQL = os.path.join(ROOT, "database", "schema.sql")

# S1-B《数据库设计文档》v1.2（SEALED）冻结：8 张业务表
FROZEN_TABLES = [
    "export_job", "health_goal", "health_record", "login_failure_state",
    "record_tag", "user_account", "user_profile", "user_session",
]

# 冻结：17 个索引 = 7 唯一 + 10 普通
FROZEN_UNIQUE_INDEXES = [
    "uk_export_token", "uk_goal_user_type_active", "uk_login_fail_username",
    "uk_record_tag", "uk_session_refresh", "uk_user_account_username",
    "uk_user_profile_user",
]
FROZEN_NORMAL_INDEXES = [
    "idx_export_purge", "idx_export_user", "idx_hr_cleanup",
    "idx_hr_user_metric_time", "idx_hr_user_time", "idx_login_fail_locked",
    "idx_session_access", "idx_session_refresh_exp", "idx_session_user",
    "idx_tag_user",
]

# 冻结：软删仅 3 张记录型表
SOFT_DELETE_TABLES = {"health_record", "record_tag", "health_goal"}
# 冻结：仅 health_goal 使用 deleted_marker
DELETED_MARKER_TABLES = {"health_goal"}

# S1-D 冻结前端布局（HBuilderX 原生）
FROZEN_FRONTEND = [
    ("pages", "dir"), ("components", "dir"), ("api", "dir"), ("store", "dir"),
    ("utils", "dir"), ("static", "dir"),
    ("pages.json", "file"), ("manifest.json", "file"),
    ("App.vue", "file"), ("main.js", "file"), ("package.json", "file"),
]

MIGRATION_REVISION = "0001_initial_schema"
HEALTH_URL = "http://127.0.0.1:5000/api/v1/health"


def _is_target_weight_col(col: str) -> bool:
    """判断列名是否属于「目标体重」字段。

    D-1 冻结：目标体重的唯一数据源是 health_goal(goal_type='weight')，
    user_profile 不得出现任何目标体重字段。
    注意：initial_weight_kg（档案「初始体重」）是档案冻结字段，**必须存在**，
    不属于目标体重，不得误判。
    """
    c = col.lower()
    if "initial" in c:
        return False
    return ("target_weight" in c) or ("weight_target" in c) or ("goal_weight" in c)


def _qid(name: str) -> str:
    """把 MySQL 标识符（库名 / 表名）转成带反引号的安全形式。

    库名来自后端配置，为避免标识符注入，先做白名单校验再引用。
    """
    s = str(name)
    if not re.fullmatch(r"[A-Za-z0-9_$]+", s):
        raise ValueError(f"非法的 MySQL 标识符：{s!r}")
    return "`" + s + "`"

# ---------------------------------------------------------------- 结果收集

RESULTS = []


def record(section, item, ok, detail=""):
    RESULTS.append((section, item, bool(ok), detail))
    return bool(ok)


def say(msg, quiet):
    if not quiet:
        print(msg)


def section(title, quiet=False):
    if not quiet:
        print()
        print("=" * 68)
        print(title)
        print("=" * 68)


# ---------------------------------------------------------------- A 工程结构

def check_structure(quiet):
    section("[A] 工程目录与关键文件（S1-D §7 冻结布局）", quiet)
    ok = 0
    total = 0
    expect = [
        ("README.md", "file"), (".gitignore", "file"),
        ("backend/app/__init__.py", "file"), ("backend/wsgi.py", "file"),
        ("backend/requirements.txt", "file"), ("backend/alembic.ini", "file"),
        ("backend/migrations/env.py", "file"),
        (f"backend/migrations/versions/{MIGRATION_REVISION}.py", "file"),
        ("backend/.env.example", "file"),
        ("backend/app/api/v1/health.py", "file"),
        ("database/schema.sql", "file"),
        ("scripts/init_db_dev.sql", "file"),
    ]
    for rel, kind in expect:
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        exist = os.path.isfile(p) if kind == "file" else os.path.isdir(p)
        total += 1
        ok += 1 if exist else 0
        record("A 工程结构", rel, exist)
        say(f"  {'PASS' if exist else 'FAIL'}  {rel}", quiet)

    # 8 张 ORM 模型文件
    for tbl in FROZEN_TABLES:
        rel = f"backend/app/models/{tbl}.py"
        exist = os.path.isfile(os.path.join(ROOT, rel.replace("/", os.sep)))
        total += 1
        ok += 1 if exist else 0
        record("A 工程结构", rel, exist)

    # 前端冻结布局
    for name, kind in FROZEN_FRONTEND:
        p = os.path.join(FRONTEND, name)
        exist = os.path.isdir(p) if kind == "dir" else os.path.isfile(p)
        total += 1
        ok += 1 if exist else 0
        record("A 前端布局", name, exist)
        say(f"  {'PASS' if exist else 'FAIL'}  frontend/{name}", quiet)

    say(f"  --> 工程结构 {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- B 运行环境

def check_runtime(quiet):
    section("[B] Python 运行环境与依赖", quiet)
    ok = total = 0

    exist = os.path.isfile(VENV_PY)
    total += 1
    ok += 1 if exist else 0
    record("B 环境", "backend/.venv/Scripts/python.exe 存在", exist)
    say(f"  {'PASS' if exist else 'FAIL'}  .venv 存在", quiet)
    if not exist:
        return ok, total

    p = subprocess.run([VENV_PY, "--version"], capture_output=True)
    ver = (p.stdout or p.stderr).decode("utf-8", "replace").strip()
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", ver)
    good = bool(m) and (int(m.group(1)), int(m.group(2))) >= (3, 11)
    total += 1
    ok += 1 if good else 0
    record("B 环境", "Python 版本 >= 3.11", good, ver)
    say(f"  {'PASS' if good else 'FAIL'}  {ver}（要求 >= 3.11）", quiet)

    # (import 名, 发行版名) —— 两者不同的必须显式给出，否则版本查询会失败
    pkgs = [
        ("flask", "Flask"), ("sqlalchemy", "SQLAlchemy"), ("alembic", "alembic"),
        ("marshmallow", "marshmallow"), ("pymysql", "PyMySQL"), ("jwt", "PyJWT"),
        ("bcrypt", "bcrypt"), ("dotenv", "python-dotenv"),
        ("cryptography", "cryptography"), ("pytest", "pytest"),
    ]
    code = (
        "import importlib, importlib.metadata as M, json\n"
        "pairs=" + repr(pkgs) + "\n"
        "out={}\n"
        "for mod, dist in pairs:\n"
        "    try:\n"
        "        importlib.import_module(mod)\n"
        "        try:\n"
        "            out[mod]=M.version(dist)\n"
        "        except Exception:\n"
        "            out[mod]='(已导入, 无发行版元数据)'\n"
        "    except Exception as e:\n"
        "        out[mod]='MISSING:'+type(e).__name__\n"
        "print('@@'+json.dumps(out))\n"
    )
    r = subprocess.run([VENV_PY, "-c", code], capture_output=True, cwd=BACKEND)
    txt = r.stdout.decode("utf-8", "replace")
    mm = re.search(r"@@(\{.*\})", txt, re.S)
    data = json.loads(mm.group(1)) if mm else {}
    for mod, _dist in pkgs:
        v = data.get(mod, "MISSING")
        good = not str(v).startswith("MISSING")
        total += 1
        ok += 1 if good else 0
        record("B 依赖", f"导入 {mod}", good, str(v))
        say(f"  {'PASS' if good else 'FAIL'}  {mod:<14} {v}", quiet)

    # Flask-SQLAlchemy 必须**不存在**（S1-D 冻结：纯原生 SQLAlchemy）
    code2 = "import importlib.util as u;print('@@', u.find_spec('flask_sqlalchemy') is None)"
    r2 = subprocess.run([VENV_PY, "-c", code2], capture_output=True, cwd=BACKEND)
    absent = "@@ True" in r2.stdout.decode("utf-8", "replace")
    total += 1
    ok += 1 if absent else 0
    record("B 依赖", "未引入 flask_sqlalchemy（冻结要求纯原生）", absent)
    say(f"  {'PASS' if absent else 'FAIL'}  未引入 flask-sqlalchemy", quiet)

    say(f"  --> 环境 {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- C ORM 元数据

def load_metadata():
    code = r'''
import json
from app.models.base import Base
md = Base.metadata
tables = sorted(md.tables.keys())
idx = []
for t in md.sorted_tables:
    for i in t.indexes:
        idx.append((i.name, t.name, bool(i.unique)))
cols = {t.name: sorted(c.name for c in t.columns) for t in md.sorted_tables}
print(json.dumps({"tables": tables, "indexes": idx, "columns": cols}))
'''
    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([VENV_PY, "-c", code], capture_output=True, cwd=BACKEND, env=env)
    out = r.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        return json.loads(out[-1]), None
    except Exception:
        return None, r.stderr.decode("utf-8", "replace")[-800:]


def check_metadata(quiet):
    section("[C] ORM 元数据（8 表 / 17 索引）", quiet)
    meta, err = load_metadata()
    ok = total = 0
    if not meta:
        record("C ORM", "读取 Base.metadata", False, err)
        say("  FAIL 无法读取 ORM 元数据: " + str(err), quiet)
        return 0, 1

    total += 1
    same = meta["tables"] == FROZEN_TABLES
    ok += 1 if same else 0
    record("C ORM", "表名集合 == 8 张冻结表", same, str(meta["tables"]))
    say(f"  {'PASS' if same else 'FAIL'}  表数 {len(meta['tables'])}（期望 8）", quiet)

    names = {n for n, _, _ in meta["indexes"]}
    uq = {n for n, _, u in meta["indexes"] if u}
    nm = {n for n, _, u in meta["indexes"] if not u}
    for label, good, detail in [
        ("索引总数 == 17", len(meta["indexes"]) == 17, len(meta["indexes"])),
        ("唯一索引 == 7 且名称吻合", uq == set(FROZEN_UNIQUE_INDEXES), sorted(uq)),
        ("普通索引 == 10 且名称吻合", nm == set(FROZEN_NORMAL_INDEXES), sorted(nm)),
    ]:
        total += 1
        ok += 1 if good else 0
        record("C ORM", label, good, str(detail))
        say(f"  {'PASS' if good else 'FAIL'}  {label}", quiet)

    # D-1：user_profile 不得出现「目标体重」字段（initial_weight_kg 是档案冻结字段，必须存在）
    prof = meta["columns"].get("user_profile", [])
    bad = [c for c in prof if _is_target_weight_col(c)]
    total += 1
    ok += 1 if not bad else 0
    record("C ORM", "D-1 user_profile 无目标体重字段", not bad, str(bad))
    say(f"  {'PASS' if not bad else 'FAIL'}  D-1 user_profile 无目标体重字段 {bad or ''}", quiet)

    total += 1
    has_initial = any("initial_weight" in c.lower() for c in prof)
    ok += 1 if has_initial else 0
    record("C ORM", "user_profile 含档案冻结字段 initial_weight_kg", has_initial, str(prof))
    say(f"  {'PASS' if has_initial else 'FAIL'}  user_profile 含 initial_weight_kg（档案初始体重）", quiet)

    # 软删字段仅 3 张表；deleted_marker 仅 health_goal
    with_sd = {t for t, cs in meta["columns"].items() if "is_deleted" in cs}
    total += 1
    good = with_sd == SOFT_DELETE_TABLES
    ok += 1 if good else 0
    record("C ORM", "软删字段仅 3 张记录型表", good, str(sorted(with_sd)))
    say(f"  {'PASS' if good else 'FAIL'}  软删字段仅在 {sorted(with_sd)}", quiet)

    with_dm = {t for t, cs in meta["columns"].items() if "deleted_marker" in cs}
    total += 1
    good2 = with_dm == DELETED_MARKER_TABLES
    ok += 1 if good2 else 0
    record("C ORM", "deleted_marker 仅 health_goal", good2, str(sorted(with_dm)))
    say(f"  {'PASS' if good2 else 'FAIL'}  deleted_marker 仅在 {sorted(with_dm)}", quiet)

    say(f"  --> ORM 元数据 {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- D 迁移 DDL

def check_migration_ddl(quiet):
    section("[D] Alembic 迁移与离线 DDL", quiet)
    ok = total = 0

    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([VENV_PY, "-m", "alembic", "heads"], cwd=BACKEND,
                       capture_output=True, env=env)
    out = r.stdout.decode("utf-8", "replace")
    good = MIGRATION_REVISION in out and "(head)" in out
    total += 1
    ok += 1 if good else 0
    record("D 迁移", "alembic heads 识别 0001_initial_schema", good, out.strip())
    say(f"  {'PASS' if good else 'FAIL'}  alembic heads -> {out.strip()}", quiet)

    if not os.path.isfile(SCHEMA_SQL):
        total += 1
        record("D 迁移", "database/schema.sql 存在", False)
        say("  FAIL  database/schema.sql 不存在", quiet)
        return ok, total

    sql = open(SCHEMA_SQL, encoding="utf-8").read()
    tabs = sorted({t for t in re.findall(r"CREATE TABLE [`\"\[]?([A-Za-z0-9_]+)", sql)
                   if t != "alembic_version"})
    uq = re.findall(r"CREATE UNIQUE INDEX [`\"\[]?([A-Za-z0-9_]+)", sql)
    nm = re.findall(r"CREATE INDEX [`\"\[]?([A-Za-z0-9_]+)", sql)

    for label, good, detail in [
        ("DDL 业务表 == 8 张且名称吻合", tabs == FROZEN_TABLES, tabs),
        ("DDL 唯一索引 == 7 且名称吻合", sorted(uq) == sorted(FROZEN_UNIQUE_INDEXES), sorted(uq)),
        ("DDL 普通索引 == 10 且名称吻合", sorted(nm) == sorted(FROZEN_NORMAL_INDEXES), sorted(nm)),
        ("DDL 不含 FOREIGN KEY（冻结要求）", "FOREIGN KEY" not in sql.upper(), ""),
        ("DDL 使用 utf8mb4_0900_ai_ci", "utf8mb4_0900_ai_ci" in sql, ""),
        ("DDL 使用 InnoDB", "InnoDB" in sql, ""),
    ]:
        total += 1
        ok += 1 if good else 0
        record("D 迁移", label, good, str(detail))
        say(f"  {'PASS' if good else 'FAIL'}  {label}", quiet)

    say(f"  --> 迁移/DDL {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- E 冒烟启动

def check_flask_smoke(quiet):
    section("[E] Flask 启动 + Y-01 GET /api/v1/health 冒烟", quiet)
    ok = total = 0

    env = {**os.environ, "APP_ENV": "development", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([VENV_PY, "wsgi.py"], cwd=BACKEND, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    body = headers = None
    try:
        for _ in range(40):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                    body = resp.read().decode("utf-8")
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    break
            except Exception:
                if proc.poll() is not None:
                    break

        good = body is not None
        total += 1
        ok += 1 if good else 0
        record("E 冒烟", "Flask 可启动且 /api/v1/health 返回 200", good)
        say(f"  {'PASS' if good else 'FAIL'}  启动并访问 {HEALTH_URL}", quiet)

        if body:
            d = json.loads(body)
            checks = [
                ("响应壳含 code/message/data/request_id",
                 sorted(d.keys()) == ["code", "data", "message", "request_id"], sorted(d.keys())),
                ("code == 'OK'", d.get("code") == "OK", d.get("code")),
                ("data.status == 'up'", (d.get("data") or {}).get("status") == "up", d.get("data")),
                ("request_id 为 32 位十六进制",
                 bool(re.fullmatch(r"[0-9a-f]{32}", str(d.get("request_id", "")))), d.get("request_id")),
                ("X-Request-Id 头存在",
                 bool(headers.get("x-request-id")), headers.get("x-request-id")),
                ("X-Request-Id 与 body.request_id 一致",
                 headers.get("x-request-id") == d.get("request_id"), ""),
            ]
            for label, good, detail in checks:
                total += 1
                ok += 1 if good else 0
                record("E 冒烟", label, good, str(detail))
                say(f"  {'PASS' if good else 'FAIL'}  {label}", quiet)

            # 未注册路径必须 404 且用统一错误壳
            try:
                urllib.request.urlopen("http://127.0.0.1:5000/api/v1/__nope__", timeout=2)
                good404, detail404 = False, "返回 2xx"
            except urllib.error.HTTPError as e:
                payload = e.read().decode("utf-8")
                good404 = (e.code == 404 and "RESOURCE_NOT_FOUND" in payload)
                detail404 = f"HTTP {e.code}"
            except Exception as e:
                good404, detail404 = False, repr(e)
            total += 1
            ok += 1 if good404 else 0
            record("E 冒烟", "未注册路径返回 404 + RESOURCE_NOT_FOUND", good404, detail404)
            say(f"  {'PASS' if good404 else 'FAIL'}  未注册路径 404 统一错误壳（{detail404}）", quiet)
        else:
            o, e2 = proc.communicate(timeout=5)
            say("  stderr: " + e2.decode("utf-8", "replace")[-600:], quiet)
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=8)
        except Exception:
            proc.kill()

    say(f"  --> 冒烟 {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- F Git 忽略

def check_gitignore(quiet):
    section("[F] .gitignore 有效性（敏感文件不入 Git）", quiet)
    import shutil
    git = shutil.which("git") or r"E:\git\Git\cmd\git.exe"
    ok = total = 0

    ignored_expect = [
        "backend/.env.development", "backend/.env.test", "backend/.env.production",
        "backend/.venv/pyvenv.cfg", "backend/logs/x.log", "frontend/node_modules/x",
        "frontend/unpackage/x", "database/x.bak", "x.pem", "x.key",
    ]
    kept_expect = ["backend/.env.example", "README.md", ".gitignore",
                   "database/schema.sql", "frontend/manifest.json"]

    for rel in ignored_expect:
        r = subprocess.run([git, "check-ignore", "-q", rel], cwd=ROOT, capture_output=True)
        good = r.returncode == 0
        total += 1
        ok += 1 if good else 0
        record("F Git", f"已忽略 {rel}", good)
        say(f"  {'PASS' if good else 'FAIL'}  已忽略  {rel}", quiet)

    for rel in kept_expect:
        r = subprocess.run([git, "add", "--dry-run", rel], cwd=ROOT, capture_output=True)
        good = r.returncode == 0
        total += 1
        ok += 1 if good else 0
        record("F Git", f"未忽略 {rel}", good)
        say(f"  {'PASS' if good else 'FAIL'}  可入库  {rel}", quiet)

    say(f"  --> Git 忽略 {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- G 数据库只读

DB_CHECKS_SQL = {
    "schema": (
        "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
        "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
        ["charset", "collation"],
    ),
    "tables": (
        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
        "AND TABLE_TYPE='BASE TABLE' AND TABLE_NAME<>'alembic_version' ORDER BY TABLE_NAME",
        ["table_name"],
    ),
    "indexes": (
        "SELECT TABLE_NAME, INDEX_NAME, MIN(NON_UNIQUE) AS non_unique "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND INDEX_NAME<>'PRIMARY' "
        "GROUP BY TABLE_NAME, INDEX_NAME ORDER BY TABLE_NAME, INDEX_NAME",
        ["table_name", "index_name", "non_unique"],
    ),
}


def check_database(quiet):
    section("[G] 数据库只读核验（A~L）", quiet)
    ok = total = 0

    sys.path.insert(0, BACKEND)
    os.environ.setdefault("APP_ENV", "development")
    try:
        from app.core.config import load_config, build_db_uri
    except Exception as e:
        record("G DB", "导入后端配置模块", False, repr(e))
        say(f"  FAIL  无法导入后端配置模块: {e!r}", quiet)
        return 0, 1

    cfg = load_config()
    dbname = cfg.get("MYSQL_DB") or "kangji_healthtrack"
    user = str(cfg.get("MYSQL_USER") or "")
    pwd = str(cfg.get("MYSQL_PASSWORD") or "")

    if not user or "CHANGE_ME" in user.upper() or not pwd or "CHANGE_ME" in pwd.upper():
        record("G DB", "MYSQL_USER / MYSQL_PASSWORD 已配置为真实值", False, "仍为占位符")
        say("  FAIL  backend/.env.development 中的 MYSQL_USER / MYSQL_PASSWORD 仍为占位符", quiet)
        say("        请先填写真实开发账号后重跑（--db）", quiet)
        return 0, 1

    try:
        import pymysql
    except Exception as e:
        say(f"  FAIL  PyMySQL 不可用: {e!r}", quiet)
        return 0, 1

    try:
        conn = pymysql.connect(host=cfg.get("MYSQL_HOST") or "127.0.0.1",
                               port=int(cfg.get("MYSQL_PORT") or 3306),
                               user=user, password=pwd, charset="utf8mb4",
                               connect_timeout=8)
    except Exception as e:
        record("G DB", f"连接 MySQL 且账号可用（{user}@host）", False, repr(e))
        say(f"  FAIL  连接失败: {e!r}", quiet)
        return 0, 1

    total += 1
    ok += 1
    record("G DB", "连接 MySQL 成功", True)
    say(f"  PASS  连接成功（{user}）", quiet)

    cur = conn.cursor()

    # A 库存在 + B 字符集
    cur.execute(DB_CHECKS_SQL["schema"][0], (dbname,))
    rows = cur.fetchall()
    good = bool(rows)
    total += 1
    ok += 1 if good else 0
    record("G DB", f"开发库 {dbname} 存在", good)
    say(f"  {'PASS' if good else 'FAIL'}  库 {dbname} 存在", quiet)
    if good:
        cs, co = rows[0]
        for label, g, det in [
            (f"字符集 == utf8mb4", str(cs).lower() == "utf8mb4", cs),
            (f"排序规则 == utf8mb4_0900_ai_ci", str(co).lower() == "utf8mb4_0900_ai_ci", co),
        ]:
            total += 1
            ok += 1 if g else 0
            record("G DB", label, g, str(det))
            say(f"  {'PASS' if g else 'FAIL'}  {label}（实际 {det}）", quiet)

        # 绑定本会话的库上下文到已验证存在的开发库。
        # 目的：L 项（alembic_version）等需要库上下文的查询不再依赖裸连接，
        #       否则会报 1046 "No database selected"。
        # 库不存在时跳过，不影响其它全限定（information_schema）查询。
        try:
            cur.execute(f"USE {_qid(dbname)}")
        except Exception as e:
            say(f"  --    未能选择库 {dbname}（{type(e).__name__}）；"
                f"非限定表名查询将改用全限定名", quiet)

    # C/D 表
    cur.execute(DB_CHECKS_SQL["tables"][0], (dbname,))
    tabs = sorted(r[0] for r in cur.fetchall())
    good = tabs == FROZEN_TABLES
    total += 1
    ok += 1 if good else 0
    record("G DB", "业务表 == 8 张且名称吻合", good, str(tabs))
    say(f"  {'PASS' if good else 'FAIL'}  业务表 {len(tabs)} 张（期望 8）: {tabs}", quiet)

    # E/F 索引
    cur.execute(DB_CHECKS_SQL["indexes"][0], (dbname,))
    irows = cur.fetchall()
    uq = sorted(n for _, n, nu in irows if int(nu) == 0)
    nm = sorted(n for _, n, nu in irows if int(nu) != 0)
    for label, g, det in [
        (f"索引总数 == 17", len(irows) == 17, len(irows)),
        ("唯一索引 == 7 且名称吻合", uq == sorted(FROZEN_UNIQUE_INDEXES), uq),
        ("普通索引 == 10 且名称吻合", nm == sorted(FROZEN_NORMAL_INDEXES), nm),
    ]:
        total += 1
        ok += 1 if g else 0
        record("G DB", label, g, str(det))
        say(f"  {'PASS' if g else 'FAIL'}  {label}", quiet)

    # 外键必须为 0
    cur.execute("SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA=%s", (dbname,))
    fk = cur.fetchone()[0]
    total += 1
    ok += 1 if fk == 0 else 0
    record("G DB", "外键数量 == 0（冻结要求）", fk == 0, fk)
    say(f"  {'PASS' if fk == 0 else 'FAIL'}  外键数量 = {fk}（期望 0）", quiet)

    # 列信息
    cur.execute("SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s", (dbname,))
    cols = {}
    for t, c in cur.fetchall():
        cols.setdefault(t, set()).add(c.lower())

    # H user_profile 无目标体重字段（D-1）
    bad = [c for c in cols.get("user_profile", set()) if _is_target_weight_col(c)]
    total += 1
    ok += 1 if not bad else 0
    record("G DB", "D-1 user_profile 无目标体重字段", not bad, str(bad))
    say(f"  {'PASS' if not bad else 'FAIL'}  D-1 user_profile 无目标体重字段 {bad or ''}", quiet)

    total += 1
    has_initial = any("initial_weight" in c for c in cols.get("user_profile", set()))
    ok += 1 if has_initial else 0
    record("G DB", "user_profile 含档案冻结字段 initial_weight_kg", has_initial)
    say(f"  {'PASS' if has_initial else 'FAIL'}  user_profile 含 initial_weight_kg（档案初始体重）", quiet)

    # I 软删字段仅 3 张表 / deleted_marker 仅 health_goal
    with_sd = sorted(t for t, cs in cols.items() if "is_deleted" in cs)
    total += 1
    ok += 1 if with_sd == sorted(SOFT_DELETE_TABLES) else 0
    record("G DB", "软删字段仅 3 张记录型表", with_sd == sorted(SOFT_DELETE_TABLES), with_sd)
    say(f"  {'PASS' if with_sd == sorted(SOFT_DELETE_TABLES) else 'FAIL'}  "
        f"is_deleted 仅在 {with_sd}", quiet)

    with_dm = sorted(t for t, cs in cols.items() if "deleted_marker" in cs)
    total += 1
    ok += 1 if with_dm == ["health_goal"] else 0
    record("G DB", "deleted_marker 仅 health_goal", with_dm == ["health_goal"], with_dm)
    say(f"  {'PASS' if with_dm == ['health_goal'] else 'FAIL'}  deleted_marker 仅在 {with_dm}", quiet)

    # J 关键唯一索引的列组成
    def idx_cols(name):
        cur.execute("SELECT COLUMN_NAME FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA=%s AND INDEX_NAME=%s ORDER BY SEQ_IN_INDEX",
                    (dbname, name))
        return [r[0].lower() for r in cur.fetchall()]

    for iname, table, expect_cols, label in [
        ("uk_user_profile_user", "user_profile", ["user_id"], "user_profile UNIQUE(user_id)"),
        ("uk_session_refresh", "user_session", ["refresh_token_hash"],
         "user_session refresh_token_hash 唯一"),
        ("uk_export_token", "export_job", ["file_token"], "export_job file_token 唯一"),
        ("uk_goal_user_type_active", "health_goal", ["user_id", "goal_type", "deleted_marker"],
         "health_goal 目标体重唯一来源（user_id+goal_type+deleted_marker）"),
    ]:
        got = idx_cols(iname)
        good = got == expect_cols
        total += 1
        ok += 1 if good else 0
        record("G DB", label, good, str(got))
        say(f"  {'PASS' if good else 'FAIL'}  {label} -> {got}", quiet)

    # K username 唯一
    got = idx_cols("uk_user_account_username")
    good = got == ["username"]
    total += 1
    ok += 1 if good else 0
    record("G DB", "user_account username 唯一", good, str(got))
    say(f"  {'PASS' if good else 'FAIL'}  user_account username 唯一 -> {got}", quiet)

    # L alembic_version
    # 必须带「库上下文」：本脚本的连接未指定 database（以便库缺失时能优雅降级），
    # 因此非限定表名 `alembic_version` 会报 OperationalError(1046, 'No database selected')。
    # 统一改为走「已配置的开发库」全限定名，查询口径与 A~K 项的 information_schema 一致。
    try:
        cur.execute(f"SELECT version_num FROM {_qid(dbname)}.alembic_version")
        rs = [r[0] for r in cur.fetchall()]
        good = rs == [MIGRATION_REVISION]
    except Exception as e:
        rs, good = repr(e), False
    total += 1
    ok += 1 if good else 0
    record("G DB", "alembic_version == 0001_initial_schema", good, str(rs))
    say(f"  {'PASS' if good else 'FAIL'}  alembic_version -> {rs}", quiet)

    cur.close()
    conn.close()
    say(f"  --> 数据库 {ok}/{total}", quiet)
    return ok, total


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="康迹 HealthTrack S2 第一批 骨架核验")
    ap.add_argument("--db", action="store_true", help="追加数据库只读核验（需已配置凭据）")
    ap.add_argument("--quiet", action="store_true", help="只输出失败项")
    args = ap.parse_args()
    quiet = args.quiet

    print("康迹 HealthTrack —— S2 第一批 骨架核验")
    print("项目根目录:", ROOT)
    print("Python:", VENV_PY)
    print("模式:", "含数据库核验" if args.db else "仅骨架（不连库）")

    results = []
    results.append(check_structure(quiet))
    results.append(check_runtime(quiet))
    results.append(check_metadata(quiet))
    results.append(check_migration_ddl(quiet))
    results.append(check_flask_smoke(quiet))
    results.append(check_gitignore(quiet))
    if args.db:
        results.append(check_database(quiet))

    pok = sum(r[0] for r in results)
    ptot = sum(r[1] for r in results)
    fails = [(s, i, d) for s, i, o, d in RESULTS if not o]

    print()
    print("=" * 68)
    print(f"总计：{pok}/{ptot} PASS，{len(fails)} FAIL")
    print("=" * 68)
    if fails:
        for s, i, d in fails:
            print(f"  FAIL  [{s}] {i}" + (f"  -> {d}" if d else ""))
    else:
        print("  全部通过。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
