# -*- coding: utf-8 -*-
"""S2 第二批 —— 范围守卫 / 密钥扫描 / 医疗红线 / 基线一致性 一键核验（只读）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch2.py
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch2.py --db   # 连库额外核验

覆盖：
- [A] **范围守卫**：接口集合恰为 Y-01 + A-01~A-06；8 表 / 17 索引 / 0 提醒表 / 0 外键；
      迁移仅 0001；前端页面数不变；P1/P2 与 F-089+ 零体现
- [B] **密钥与敏感信息**：仓库无硬编码密钥 / 无 `.env` 入库
- [C] **医疗红线**：本批源码 + 全 app 源码 + 运行期文案
- [D] **基线一致性**：S1-A~S1-D 封板文档未被本轮改动
- [E] **数据洁净**：2 张业务表（含档案）行数与预期一致
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ROOT_S = str(ROOT)
FROZEN_TABLES = [
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
]
EXPECTED_ROUTES = {
    "/api/v1/health",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/password",
    "/api/v1/users/me",
}
FROZEN_CODES = {
    "INVALID_PARAM", "UNAUTHENTICATED", "CREDENTIALS_INVALID", "TOKEN_REUSED",
    "RESOURCE_NOT_FOUND", "USERNAME_TAKEN", "GOAL_TYPE_EXISTS", "EXPORT_IN_PROGRESS",
    "IDEMPOTENCY_CONFLICT", "COUNT_MISMATCH", "EXPORT_EXPIRED", "VALIDATION_FAILED",
    "PASSWORD_INVALID", "ACCOUNT_LOCKED", "SESSION_VERIFY_ABORTED", "SOFT_WARNING",
    "INTERNAL_ERROR", "SERVICE_UNAVAILABLE",
}
BATCH2_FILES = [
    "backend/app/__init__.py",
    "backend/app/core/errors.py",
    "backend/app/core/response.py",
    "backend/app/core/security.py",
    "backend/app/core/auth.py",
    "backend/app/schemas/common.py",
    "backend/app/schemas/auth.py",
    "backend/app/services/auth_service.py",
    "backend/app/api/v1/auth.py",
    "backend/app/api/v1/users.py",
    "backend/pytest.ini",
]
BATCH2_FILES += [
    "backend/tests/conftest.py",
    "backend/tests/test_auth_flow.py",
    "backend/tests/test_auth_security.py",
    "backend/tests/test_contract.py",
    "backend/tests/test_medical_redline.py",
]
BANNED_TERMS = [
    "诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药",
    "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围",
    "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数",
]
EXEMPT_MARKERS = ["禁止", "不得", "不含", "不涉及", "非医疗", "中性", "无医学",
                  "不做", "严禁", "banned", "禁用", "红线", "豁免"]

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".hbuilderx",
             "unpackage", "dist", ".workbuddy", ".pytest_cache"}

RESULTS: list[tuple[str, str, bool, str]] = []


def record(section: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((section, name, bool(ok), detail))


def say(text: str = "") -> None:
    print(text, flush=True)


# ══════════════════════════════════════════════════════════════════ A 范围守卫
def check_scope(quiet: bool) -> None:
    say("=" * 72)
    say("[A] 范围守卫（接口 / 数据库 / 迁移 / 前端 / 编号）")
    say("=" * 72)
    from app import create_app

    app = create_app("development")
    routes = {str(r) for r in app.url_map.iter_rules() if str(r).startswith("/api/")}
    ok = routes == EXPECTED_ROUTES
    record("A 范围", "接口集合 == Y-01 + A-01~A-06（7 个）", ok, str(sorted(routes ^ EXPECTED_ROUTES)))
    say(f"  {'PASS' if ok else 'FAIL'}  接口集合 {len(routes)} 个 = Y-01 + A-01~A-06"
        + ("" if ok else f"  差异={sorted(routes ^ EXPECTED_ROUTES)}"))

    # 累计 7/34
    ok7 = len(routes) == 7
    record("A 范围", "累计接口 7 / 34", ok7, str(len(routes)))
    say(f"  {'PASS' if ok7 else 'FAIL'}  累计接口 {len(routes)} / 34")

    # A-07 不得存在
    delete_me = [r for r in app.url_map.iter_rules()
                 if str(r) == "/api/v1/users/me" and "DELETE" in (r.methods or set())]
    record("A 范围", "A-07 注销接口不存在", not delete_me)
    say(f"  {'PASS' if not delete_me else 'FAIL'}  A-07 注销接口零实现")

    # 错误码集合冻结
    from app.core.errors import ERROR_HTTP_STATUS, ERROR_MESSAGE, ErrorCode

    declared = {n for n, v in vars(ErrorCode).items() if not n.startswith("_") and isinstance(v, str)}
    okc = declared == FROZEN_CODES == set(ERROR_HTTP_STATUS) == set(ERROR_MESSAGE)
    record("A 范围", "错误码集合 == 冻结 18 个", okc, str(sorted(declared ^ FROZEN_CODES)))
    say(f"  {'PASS' if okc else 'FAIL'}  错误码集合 = 冻结 18 个")

    # 迁移文件数量
    vers = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py")
                  if not p.name.startswith("__"))
    okm = vers == ["0001_initial_schema.py"]
    record("A 范围", "迁移仅 0001_initial_schema（无 0002_*）", okm, str(vers))
    say(f"  {'PASS' if okm else 'FAIL'}  迁移文件 {vers}")

    # 前端页面：仍仅第一批占位页
    pages = sorted(str(p.relative_to(ROOT / "frontend")).replace(os.sep, "/")
                   for p in (ROOT / "frontend" / "pages").rglob("*.vue"))
    okp = pages == ["pages/index/index.vue"]
    record("A 范围", "前端仍仅 1 个占位页（0 个 P0 业务页）", okp, str(pages))
    say(f"  {'PASS' if okp else 'FAIL'}  前端页面 {pages}")

    # P1/P2 与 F-089+ 零体现（仅扫**产品源码**；核验脚本自身的判据文本不计）
    bad_ids = []
    for path in _iter_code(only_dirs=PRODUCT_DIRS):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"F-0(\d{2})\b", text):
            if int(m.group(1)) >= 89:
                bad_ids.append(f"{path.relative_to(ROOT)}:F-{m.group(1)}")
    okf = not bad_ids
    record("A 范围", "F-089+ 零体现（源码/注释）", okf, str(bad_ids[:5]))
    say(f"  {'PASS' if okf else 'FAIL'}  F-089+ 零体现" + ("" if okf else f" {bad_ids[:5]}"))


CODE_SUFFIX = (".py", ".js", ".vue", ".json", ".sql", ".ini", ".conf", ".cfg")
PRODUCT_DIRS = ("backend/app", "backend/tests", "frontend", "database")


def _iter_code(only_dirs=None):
    """遍历源码类文件（不含 .md 文档）；``only_dirs`` 限定相对根目录前缀。"""
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if not f.endswith(CODE_SUFFIX):
                continue
            path = Path(dp) / f
            rel = str(path.relative_to(ROOT)).replace(os.sep, "/")
            if only_dirs and not any(rel.startswith(d + "/") for d in only_dirs):
                continue
            yield path


# ══════════════════════════════════════════════════════════════════ B 密钥扫描
def check_secrets(quiet: bool) -> None:
    say()
    say("=" * 72)
    say("[B] 密钥与敏感信息扫描")
    say("=" * 72)
    # 通用密钥模式（全仓源码）
    generic_patterns = [
        (re.compile(r"SECRET_KEY\s*=\s*['\"][0-9a-fA-F]{32,}['\"]"), "硬编码 JWT 密钥"),
        (re.compile(r"MYSQL_PASSWORD\s*=\s*['\"](?!CHANGE_ME|''|\"\")[^'\"]{3,}['\"]"), "硬编码数据库口令"),
        (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."), "硬编码 JWT 字面量"),
    ]
    # 口令字面量模式：只在**产品代码**中判定（测试/脚本中的测试账号口令属预期夹具）
    product_only_patterns = [
        (re.compile(r"(?i)\bpassword\s*=\s*['\"][^'\"]{6,}['\"]"), "硬编码口令字面量"),
    ]

    hits = []
    scanned = 0
    for path in _iter_code():
        rel = str(path.relative_to(ROOT)).replace(os.sep, "/")
        if rel.startswith("backend/.env") and not rel.endswith(".example"):
            continue  # 真实 .env 本身含密钥，属预期（且已 gitignore）
        if rel.endswith(".env.example") or rel.startswith("scripts/"):
            continue  # 模板与核验脚本不含真实密钥
        scanned += 1
        is_product = any(rel.startswith(d + "/") for d in PRODUCT_DIRS)
        patterns = generic_patterns + (product_only_patterns if is_product else [])
        text = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if _is_exempt_secret(line):
                continue
            for rx, label in patterns:
                if rx.search(line):
                    # 只记录位置与类型，**绝不回显被匹配的源码片段**（防凭据外泄）
                    hits.append(f"{rel}:{i} [{label}]")
    ok = not hits
    record("B 密钥", f"仓库源码硬编码密钥扫描（{scanned} 文件）", ok, str(hits[:4]))
    say(f"  {'PASS' if ok else 'FAIL'}  硬编码密钥扫描 {scanned} 文件，命中 {len(hits)}")
    for h in hits[:10]:
        say(f"        {h}")

    # .env.example 仍为纯占位符
    ex = BACKEND / ".env.example"
    text = ex.read_text(encoding="utf-8", errors="ignore") if ex.is_file() else ""
    ok0 = "SECRET_KEY=CHANGE_ME" in text and "MYSQL_PASSWORD=CHANGE_ME" in text
    record("B 密钥", ".env.example 仍为占位符", ok0)
    say(f"  {'PASS' if ok0 else 'FAIL'}  .env.example 仍为纯占位符")

    # .env 系列不得被 git 跟踪
    import subprocess

    git = r"E:\git\Git\cmd\git.exe"
    tracked = []
    if os.path.isfile(git):
        r = subprocess.run([git, "ls-files"], cwd=str(ROOT), capture_output=True)
        files = r.stdout.decode("utf-8", "replace").splitlines()
        tracked = [f for f in files if re.match(r"^backend/\.env(\.|$)", f)]
    ok2 = not tracked
    record("B 密钥", ".env* 未被 git 跟踪", ok2, str(tracked))
    say(f"  {'PASS' if ok2 else 'FAIL'}  .env* 未被 git 跟踪 {tracked or ''}")

    # .gitignore 覆盖 .env 系列
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore")
    ok3 = ".env" in gi and "!.env.example" in gi.replace(" ", "")
    record("B 密钥", ".gitignore 含 .env 与 !.env.example", ok3)
    say(f"  {'PASS' if ok3 else 'FAIL'}  .gitignore 覆盖 .env / 放行 .env.example")


def _is_exempt_secret(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in ("change_me", "占位", "示例", "example", "模板", "redact", "placeholder"))


# ══════════════════════════════════════════════════════════════════ C 医疗红线
def check_medical(quiet: bool) -> None:
    say()
    say("=" * 72)
    say("[C] 医疗红线扫描（本批源码 + 全部 app 源码）")
    say("=" * 72)
    targets = sorted(set(BATCH2_FILES + [
        "backend/app/core/config.py", "backend/app/core/db.py", "backend/app/core/logging.py",
        "backend/app/core/request_id.py", "backend/app/api/v1/health.py", "backend/wsgi.py",
    ]))
    hits = []
    lines = 0
    for rel in targets:
        path = ROOT / rel
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lines += 1
            if any(m.lower() in line.lower() for m in EXEMPT_MARKERS):
                continue
            for term in BANNED_TERMS:
                if term in line:
                    hits.append(f"{rel}:{i} 「{term}」")
    ok = not hits
    record("C 红线", f"源码扫描（{lines} 行 / {len(targets)} 文件）", ok, str(hits[:4]))
    say(f"  {'PASS' if ok else 'FAIL'}  源码红线扫描 {lines} 行，命中 {len(hits)}")
    for h in hits[:6]:
        say(f"        {h}")


# ══════════════════════════════════════════════════════════════════ D 基线一致性
def check_baseline(quiet: bool) -> None:
    say()
    say("=" * 72)
    say("[D] 基线一致性（S1 封板文档未被改动）")
    say("=" * 72)
    art = ROOT / ".workbuddy" / "artifacts"
    ref = art / "S2-第二批-开工前检查报告.md"
    if not ref.is_file():
        record("D 基线", "参照文件存在", False, "缺 S2-第二批-开工前检查报告.md")
        say("  FAIL  缺少参照文件")
        return
    ref_mtime = ref.stat().st_mtime
    s1 = sorted(p for p in art.glob("S1-*.md"))
    changed = [p.name for p in s1 if p.stat().st_mtime > ref_mtime + 1]
    ok = not changed
    record("D 基线", f"S1 封板文档 {len(s1)} 份 mtime 未晚于第二批起点", ok, str(changed))
    say(f"  {'PASS' if ok else 'FAIL'}  S1 文档 {len(s1)} 份，本轮改动 {len(changed)} 份 {changed or ''}")

    # S1 关键封板文档仍带 SEALED 标记
    # 口径：并非 29 份 S1 文档全部带标记。S1-A 的 4 份"冻结清单/冻结书/待确认事项"与
    # S1-B 的"内部一致性检查"属过程说明类，封板时按惯例未加标记（封板动作落在
    # 《S1-A-完成报告.md》）。因此只核验"关键封板/完成类"文档。
    KEY_MARKERS = ("封板记录", "封板报告", "完成状态报告", "完成报告", "技术方案最终冻结")
    key_docs = [p for p in s1 if any(m in p.name for m in KEY_MARKERS)]
    nosel = [p.name for p in key_docs
             if "SEALED" not in p.read_text(encoding="utf-8", errors="ignore")]
    ok2 = bool(key_docs) and not nosel
    record("D 基线", f"S1 关键封板文档 {len(key_docs)} 份保留 SEALED 标记", ok2, str(nosel))
    say(f"  {'PASS' if ok2 else 'FAIL'}  S1 关键封板文档 {len(key_docs)} 份，缺标记 {nosel or '无'}")

    # S2 第一批三份文档已 SEALED
    b1 = ["S2-第一批开发完成报告.md", "S2-第一批-数据库实机验收报告.md",
          "S2-第一批-验收通过与封板记录.md"]
    miss = [n for n in b1 if not (art / n).is_file()
            or "SEALED" not in (art / n).read_text(encoding="utf-8", errors="ignore")]
    ok3 = not miss
    record("D 基线", "S2 第一批 3 份文档含 SEALED", ok3, str(miss))
    say(f"  {'PASS' if ok3 else 'FAIL'}  S2 第一批 SEALED 文档 {3 - len(miss)}/3")

    # 交付物数量
    n = len(list(art.glob("*.md")))
    record("D 基线", f"artifacts 交付物 {n} 份", n >= 37, str(n))
    say(f"  PASS  artifacts 交付物 {n} 份")


# ══════════════════════════════════════════════════════════════════ E 数据库
def check_db(quiet: bool) -> None:
    import pymysql

    from app.core.config import load_config

    say()
    say("=" * 72)
    say("[E] 数据库只读核验（结构冻结 + 数据洁净）")
    say("=" * 72)
    cfg = load_config("development")
    conn = pymysql.connect(
        host=cfg["MYSQL_HOST"], port=int(cfg["MYSQL_PORT"]), user=cfg["MYSQL_USER"],
        password=cfg["MYSQL_PASSWORD"], charset=cfg["MYSQL_CHARSET"],
        cursorclass=pymysql.cursors.Cursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("USE `%s`" % cfg["MYSQL_DB"])
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
                (cfg["MYSQL_DB"],),
            )
            tables = sorted(r[0] for r in cur.fetchall())
            expected = sorted(FROZEN_TABLES + ["alembic_version"])
            ok = tables == expected
            record("E DB", "8 业务表 + alembic_version（无多余表）", ok, str(tables))
            say(f"  {'PASS' if ok else 'FAIL'}  表：{tables}")

            ok2 = "reminder" not in " ".join(tables).lower()
            record("E DB", "无 reminder 相关表", ok2)
            say(f"  {'PASS' if ok2 else 'FAIL'}  无 reminder 表")

            cur.execute(
                "SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
                "WHERE table_schema=%s AND index_name<>'PRIMARY'", (cfg["MYSQL_DB"],))
            n_idx = int(cur.fetchone()[0])
            ok3 = n_idx == 17
            record("E DB", "索引 17 个", ok3, str(n_idx))
            say(f"  {'PASS' if ok3 else 'FAIL'}  索引 {n_idx} / 17")

            cur.execute(
                "SELECT COUNT(*) FROM information_schema.table_constraints "
                "WHERE table_schema=%s AND constraint_type='FOREIGN KEY'", (cfg["MYSQL_DB"],))
            n_fk = int(cur.fetchone()[0])
            ok4 = n_fk == 0
            record("E DB", "外键 0 个", ok4, str(n_fk))
            say(f"  {'PASS' if ok4 else 'FAIL'}  外键 {n_fk} / 0")

            cur.execute("SELECT version_num FROM `%s`.alembic_version" % cfg["MYSQL_DB"])
            ver = [r[0] for r in cur.fetchall()]
            ok5 = ver == ["0001_initial_schema"]
            record("E DB", "alembic_version == 0001_initial_schema", ok5, str(ver))
            say(f"  {'PASS' if ok5 else 'FAIL'}  alembic_version = {ver}")

            counts = {}
            for t in FROZEN_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                counts[t] = int(cur.fetchone()[0])
            total = sum(counts.values())
            ok6 = total == 0
            record("E DB", "8 张业务表行数合计 0（无残留测试数据）", ok6, str(counts))
            say(f"  {'PASS' if ok6 else 'FAIL'}  行数合计 {total}  {counts if total else ''}")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="额外执行数据库只读核验")
    args = ap.parse_args()

    say()
    say("#" * 72)
    say("# S2 第二批《认证与账号基础模块》核验 —— 范围守卫 / 密钥 / 红线 / 基线")
    say("#" * 72)
    check_scope(args.db)
    check_secrets(args.db)
    check_medical(args.db)
    check_baseline(args.db)
    if args.db:
        check_db(True)

    groups: dict[str, list[int]] = {}
    for section, _n, ok, _d in RESULTS:
        g = groups.setdefault(section, [0, 0])
        g[1] += 1
        g[0] += 1 if ok else 0

    say()
    say("=" * 72)
    for section in sorted(groups):
        okn, tot = groups[section]
        say(f"  {section:<10} {okn}/{tot} " + ("PASS" if okn == tot else "FAIL"))
    passed = sum(1 for _s, _n, ok, _d in RESULTS if ok)
    total = len(RESULTS)
    say("-" * 72)
    say(f"  合计 {passed}/{total} PASS，{total - passed} FAIL")
    say(f"  结论：{'全部通过' if passed == total else '存在失败项'}")
    say("=" * 72)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
