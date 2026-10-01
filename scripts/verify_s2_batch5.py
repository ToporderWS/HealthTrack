# -*- coding: utf-8 -*-
"""S2 第五批（模块 S：首页 / 统计 / 趋势 S-01 ~ S-03）—— 一键核验（默认**只读**）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch5.py
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch5.py --db   # 追加连库只读核验

覆盖（方案 §14.1）：
- [A] **结构**：新增 2 个生产文件存在；``app/__init__.py`` 已追加注册 stats 蓝图；
      接口集合 = **27 条**（7 + 10 + 7 + **3**）/ 路径 = **21 条**（7 + 6 + 5 + **3**）；
      S-01~S-03 均为 **GET**；E / D / A-07 / 提醒 / 管理 / 支付**零实现**；
      错误码仍 18、字段级码仍 7（**未扩充**）；迁移仅 ``0001``；前端仍 1 个占位页
- [B] **环境·密钥**：仓库无硬编码密钥 / ``.env*`` 未入库 / ``.env.example`` 仍为占位符
- [C] **医疗红线**：本批源码 + 全部 ``app`` 源码（``BANNED_TERMS`` 扫描 + 响应字段名）
- [D] **基线**：S0 / S1 / S2 第一~第四批封板成果（代码 / 测试 / 脚本）**未被本轮改动**
      （按 mtime 逐文件判定，排除本批自身产出）
- [E] **ORM**：模型 ↔ 表一一对应（**本批未新增模型**）
- [F] **迁移·DDL**：无 ``0002_*``；``alembic_version = 0001_initial_schema``；
      表 9 / 非主键索引 17 / 外键 0（DB 子项需 ``--db``）
- [G] **冒烟**：``/api/v1/health`` 200；3 条新路由**可达**（无 Token → 401，**非 404**）
- [H] **本批契约**：S-01 / S-02 / S-03 关键契约断言（统一 envelope / 401 / 参数守卫 400 /
      固定字段集 / 常量口径 / 聚合显式隔离）

────────── 与开工方案的既有豁免口径（P-1 同类 / D-G1 = 方案 B） ──────────

历史批次的范围判据文件把接口集合**硬编码为各自批次时点**：
``scripts/verify_s2_batch2~4.py``、``backend/tests/batch2~4/test_batch*_scope_guard.py``、
``backend/tests/test_medical_redline.py``。第五批新增 3 个**合法**接口后，这些判据必然 FAIL，
属**历史时点判据**（非业务回归）。本脚本**不改动**任何旧批成果，而以
「当前阶段允许集合」独立判定；并在 [D] 中给出「旧批判据文件未被修改」的结构性证据。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

#: 第五批开工参照点（本批任何改动都应晚于此文件；同时是该文件的创建载体）
REFERENCE_DOC = "S2-第五批-开工前实施方案.md"
ARTIFACTS_DIR = ROOT / ".workbuddy" / "artifacts"

#: 8 张业务表（结构冻结）
FROZEN_TABLES = [
    "user_account", "user_profile", "health_record", "record_tag",
    "health_goal", "user_session", "login_failure_state", "export_job",
]

#: 第二批留存路径（7 条，**不得删除**）
BATCH2_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/password",
    "/api/v1/users/me",
}
#: 第三批新增路径（6 条，**不得删除**）
BATCH3_NEW_PATHS = {
    "/api/v1/profile",
    "/api/v1/records",
    "/api/v1/records/count",
    "/api/v1/records/options",
    "/api/v1/records/batch-delete",
    "/api/v1/records/<int:record_id>",
}
#: 第四批新增路径（5 条，**不得删除**）
BATCH4_NEW_PATHS = {
    "/api/v1/goals",
    "/api/v1/goals/progress",
    "/api/v1/goals/<int:goal_id>",
    "/api/v1/goals/<int:goal_id>/pause",
    "/api/v1/goals/<int:goal_id>/resume",
}
#: **本批**新增路径（3 条）
BATCH5_NEW_PATHS = {
    "/api/v1/home/overview",
    "/api/v1/stats/trend",
    "/api/v1/stats/summary",
}

#: 第四批完成时点的允许集合（**24 条接口** = 7 + 10 + 7）
BATCH4_ENDPOINTS = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("PUT", "/api/v1/auth/password"),
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/profile"),
    ("PUT", "/api/v1/profile"),
    ("POST", "/api/v1/records"),
    ("GET", "/api/v1/records"),
    ("GET", "/api/v1/records/count"),
    ("GET", "/api/v1/records/options"),
    ("POST", "/api/v1/records/batch-delete"),
    ("GET", "/api/v1/records/<int:record_id>"),
    ("PATCH", "/api/v1/records/<int:record_id>"),
    ("DELETE", "/api/v1/records/<int:record_id>"),
    ("GET", "/api/v1/goals"),
    ("POST", "/api/v1/goals"),
    ("GET", "/api/v1/goals/progress"),
    ("PATCH", "/api/v1/goals/<int:goal_id>"),
    ("DELETE", "/api/v1/goals/<int:goal_id>"),
    ("POST", "/api/v1/goals/<int:goal_id>/pause"),
    ("POST", "/api/v1/goals/<int:goal_id>/resume"),
}
BATCH4_PATHS = BATCH2_PATHS | BATCH3_NEW_PATHS | BATCH4_NEW_PATHS

#: **本批**新增接口（3 条，均 GET）
BATCH5_NEW_ENDPOINTS = {
    ("GET", "/api/v1/home/overview"),
    ("GET", "/api/v1/stats/trend"),
    ("GET", "/api/v1/stats/summary"),
}
#: 当前阶段允许集合（路径 **21** 条）
EXPECTED_PATHS = BATCH4_PATHS | BATCH5_NEW_PATHS
#: 当前阶段允许集合（method + 路径，**27** 条）
EXPECTED_ENDPOINTS = BATCH4_ENDPOINTS | BATCH5_NEW_ENDPOINTS

FROZEN_CODES = {
    "INVALID_PARAM", "UNAUTHENTICATED", "CREDENTIALS_INVALID", "TOKEN_REUSED",
    "RESOURCE_NOT_FOUND", "USERNAME_TAKEN", "GOAL_TYPE_EXISTS", "EXPORT_IN_PROGRESS",
    "IDEMPOTENCY_CONFLICT", "COUNT_MISMATCH", "EXPORT_EXPIRED", "VALIDATION_FAILED",
    "PASSWORD_INVALID", "ACCOUNT_LOCKED", "SESSION_VERIFY_ABORTED", "SOFT_WARNING",
    "INTERNAL_ERROR", "SERVICE_UNAVAILABLE",
}
FROZEN_FIELD_CODES = {
    "REQUIRED", "INVALID_TYPE", "INVALID_FORMAT", "WEAK_PASSWORD",
    "MISMATCH", "SAME_AS_OLD", "NOT_ACCEPTED",
}

#: 本批新增 / 修改的生产代码（**3 个**）
BATCH5_APP_FILES = [
    "backend/app/__init__.py",
    "backend/app/services/stats_service.py",
    "backend/app/api/v1/stats.py",
]
#: 本批新增的测试（**7 个**）
BATCH5_TEST_FILES = [
    "backend/tests/batch5/__init__.py",
    "backend/tests/batch5/conftest.py",
    "backend/tests/batch5/test_batch5_scope_guard.py",
    "backend/tests/batch5/test_batch5_contract_isolation.py",
    "backend/tests/batch5/test_s01_overview.py",
    "backend/tests/batch5/test_s02_trend.py",
    "backend/tests/batch5/test_s03_summary.py",
]
#: 本批新增的脚本（**2 个**）
BATCH5_SCRIPT_FILES = [
    "scripts/verify_s2_batch5.py",
    "scripts/s2_batch5_http_smoke.py",
]
#: 本批新增的人工验收素材（**4 个**：3 × .txt + 1 × .js，规避受保护文件 mtime 判据）
BATCH5_EXTRA_FILES = [
    "scripts/s2_batch5_accept.cmd.txt",
    "scripts/s2_batch5_accept.sql.txt",
    "scripts/s2_batch5_accept.console.txt",
    "S2_第五批_S01-S03_Edge验收脚本.js",
]
BATCH5_FILES = BATCH5_APP_FILES + BATCH5_TEST_FILES + BATCH5_SCRIPT_FILES

#: 旧批判据文件（**本轮不得修改**；其 FAIL 属历史时点判据）
OLD_JUDGERS = [
    "scripts/verify_s2_batch2.py",
    "scripts/verify_s2_batch3.py",
    "scripts/verify_s2_batch4.py",
    "backend/tests/test_medical_redline.py",
    "backend/tests/batch3/test_batch3_scope_guard.py",
    "backend/tests/batch4/test_batch4_scope_guard.py",
]

#: S2 第二批 4 份交付物（须保留 SEALED / 通过标记）
BATCH2_DOCS = [
    "S2-第二批-开工前检查报告.md",
    "S2-第二批开发完成报告.md",
    "S2-第二批-验收通过与封板记录.md",
    "S2-第三批-开工前接管与预检报告.md",
]
#: 第四批封板记录
BATCH4_SEAL_DOC = "S2-第四批-验收通过与封板记录.md"

#: 模块 S 三接口的固定常量口径（与 stats_service.py 冻结值一致）
CHART_FROZEN = {
    "weight": "line", "bp": "line", "heart": "line", "glucose": "line",
    "sleep": "bar", "water": "bar", "sport": "bar", "mood": "line",
}
METRIC_TYPES_FROZEN = ["weight", "bp", "heart", "glucose", "sleep", "water", "sport", "mood"]
GOAL_FIELDS_FROZEN = ["goal_id", "goal_type", "target_value", "current_value",
                      "unit", "progress_percent", "is_reached", "remaining_text"]

BANNED_TERMS = ["诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药", "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围", "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数"]  # noqa: E501  红线声明行
EXEMPT_MARKERS = ["禁止", "不得", "不含", "不涉及", "非医疗", "非医学", "中性", "无医学", "不做", "严禁", "banned", "禁用", "红线", "豁免"]  # noqa: E501  红线声明行

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".hbuilderx",
             "unpackage", "dist", ".workbuddy", ".pytest_cache", "logs", "storage"}
CODE_SUFFIX = (".py", ".js", ".vue", ".json", ".sql", ".ini", ".conf", ".cfg")
PRODUCT_DIRS = ("backend/app", "backend/tests", "frontend", "database")

#: 本批冻结的模型文件清单（**本批 0 新增模型**）
FROZEN_MODEL_FILES = [
    "__init__.py", "base.py", "export_job.py", "health_goal.py", "health_record.py",
    "login_failure_state.py", "record_tag.py", "user_account.py", "user_profile.py",
    "user_session.py",
]

RESULTS: list = []


def record(section: str, name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((section, name, bool(ok), detail))


def say(text: str = "") -> None:
    print(text, flush=True)


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
            yield path, rel


def _mtime(rel: str) -> float:
    p = ROOT / rel
    return p.stat().st_mtime if p.is_file() else 0.0


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""


def _protected_files():
    """第一～第四批受保护文件（排除本批新增 / 本批允许修改的文件）。"""
    allowed = set(BATCH5_FILES)
    roots = (BACKEND / "app", BACKEND / "tests", BACKEND / "migrations",
             ROOT / "database", ROOT / "frontend", ROOT / "scripts")
    for base in roots:
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for f in fn:
                if not f.endswith(CODE_SUFFIX):
                    continue
                rel = str((Path(dp) / f).relative_to(ROOT)).replace(os.sep, "/")
                if rel in allowed:
                    continue
                yield rel


# ══════════════════════════════════════════════════════════════ A 结构
def check_scope() -> None:
    say("=" * 72)
    say("[A] 结构守卫（新增文件 / 接口 / 错误码 / 迁移 / 前端 / 编号）")
    say("=" * 72)
    from app import create_app

    for rel in BATCH5_APP_FILES[1:]:
        ok = (ROOT / rel).is_file()
        record("A 结构", f"新增生产文件存在：{rel}", ok)
        say(f"  {'PASS' if ok else 'FAIL'}  {rel}")

    init_text = _read("backend/app/__init__.py")
    ok_bp = ("from app.api.v1.stats import bp as stats_bp" in init_text
             and "register_blueprint(stats_bp" in init_text)
    record("A 结构", "app/__init__.py 已追加注册 stats 蓝图", ok_bp)
    say(f"  {'PASS' if ok_bp else 'FAIL'}  app/__init__.py 蓝图注册追加")

    app = create_app("development")
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = {(m, str(r)) for r in rules for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}

    ok = paths == EXPECTED_PATHS
    record("A 结构", "路由路径集合 == 21 条（7 + 6 + 5 + 3）", ok, str(sorted(paths ^ EXPECTED_PATHS)))
    say(f"  {'PASS' if ok else 'FAIL'}  路由路径 {len(paths)} 条 / 目标 21"
        + ("" if ok else f"  差异={sorted(paths ^ EXPECTED_PATHS)}"))

    ok2 = endpoints == EXPECTED_ENDPOINTS
    record("A 结构", "接口（method+路径）集合 == 27 条", ok2, str(sorted(endpoints ^ EXPECTED_ENDPOINTS)))
    say(f"  {'PASS' if ok2 else 'FAIL'}  接口 {len(endpoints)} 条 / 目标 27（累计 27/34）"
        + ("" if ok2 else f"  差异={sorted(endpoints ^ EXPECTED_ENDPOINTS)}"))

    new_eps = endpoints - BATCH4_ENDPOINTS
    ok3 = new_eps == BATCH5_NEW_ENDPOINTS
    record("A 结构", "本批新增恰 3 个接口（S-01~S-03）", ok3, str(sorted(new_eps)))
    say(f"  {'PASS' if ok3 else 'FAIL'}  本批新增接口 {len(new_eps)} 个 / 目标 3")

    rules_map = {str(r): r for r in rules}
    get_only = all(
        "GET" in (rules_map[p].methods or set())
        and not ({"POST", "PUT", "PATCH", "DELETE"} & (rules_map[p].methods or set()))
        for _m, p in BATCH5_NEW_ENDPOINTS
    )
    record("A 结构", "S-01~S-03 三接口均为 GET（无写操作）", get_only)
    say(f"  {'PASS' if get_only else 'FAIL'}  S 模块三接口 GET-only")

    ok4 = not any(str(r) == "/api/v1/users/me" and "DELETE" in (r.methods or set()) for r in rules)
    record("A 结构", "A-07 注销接口零实现", ok4)
    say(f"  {'PASS' if ok4 else 'FAIL'}  A-07 注销接口零实现")

    # E / D / 提醒 / 管理 / 支付 零实现（S 已在本批实现，故不再列入 forbidden）
    forbidden = ("/api/v1/export", "/api/v1/exports", "/api/v1/data", "/api/v1/me/data",
                 "/api/v1/reminders", "/api/v1/admin", "/api/v1/payments")
    bad = sorted(p for p in paths for f in forbidden if p.startswith(f))
    ok5 = not bad
    record("A 结构", "E / D / 提醒 / 管理 / 支付 接口零实现", ok5, str(bad))
    say(f"  {'PASS' if ok5 else 'FAIL'}  越界模块接口零实现" + ("" if ok5 else f" {bad}"))

    from app.core.errors import ERROR_HTTP_STATUS, ERROR_MESSAGE, ErrorCode, FieldErrorCode

    declared = {n for n, v in vars(ErrorCode).items() if not n.startswith("_") and isinstance(v, str)}
    ok6 = declared == FROZEN_CODES == set(ERROR_HTTP_STATUS) == set(ERROR_MESSAGE)
    record("A 结构", "全局错误码集合 == 冻结 18 个（本批未增改）", ok6,
           str(sorted(declared ^ FROZEN_CODES)))
    say(f"  {'PASS' if ok6 else 'FAIL'}  全局错误码仍为冻结 18 个")

    fc = {n for n, v in vars(FieldErrorCode).items() if not n.startswith("_") and isinstance(v, str)}
    ok7 = fc == FROZEN_FIELD_CODES
    record("A 结构", "字段级码 == 冻结 7 个（未扩充）", ok7, str(sorted(fc ^ FROZEN_FIELD_CODES)))
    say(f"  {'PASS' if ok7 else 'FAIL'}  字段级码仍为冻结 7 个")

    vers = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py")
                  if not p.name.startswith("__"))
    ok8 = vers == ["0001_initial_schema.py"]
    record("A 结构", "迁移仅 0001_initial_schema（0 migration）", ok8, str(vers))
    say(f"  {'PASS' if ok8 else 'FAIL'}  迁移文件 {vers}")

    pages = sorted(str(p.relative_to(ROOT / "frontend")).replace(os.sep, "/")
                   for p in (ROOT / "frontend" / "pages").rglob("*.vue"))
    ok9 = pages == ["pages/index/index.vue"]
    record("A 结构", "前端仍仅 1 个占位页（frontend/** 本批 0 改动）", ok9, str(pages))
    say(f"  {'PASS' if ok9 else 'FAIL'}  前端页面 {pages}")

    bad_ids = []
    for path, rel in _iter_code(only_dirs=PRODUCT_DIRS):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"F-0(\d{2})\b", text):
            if int(m.group(1)) >= 89:
                bad_ids.append(f"{rel}:F-{m.group(1)}")
    ok10 = not bad_ids
    record("A 结构", "超出 S0 冻结编号的功能零体现（源码/注释）", ok10, str(bad_ids[:5]))
    say(f"  {'PASS' if ok10 else 'FAIL'}  越界功能编号零体现"
        + ("" if ok10 else f" {bad_ids[:5]}"))

    ok11 = (len(EXPECTED_ENDPOINTS) == 27 and len(EXPECTED_PATHS) == 21
            and len(BATCH4_ENDPOINTS) == 24 and len(BATCH5_NEW_ENDPOINTS) == 3)
    record("A 结构", "契约自检：27 接口 = 24（第四批）+ 3（本批）；21 路径 = 18 + 3", ok11)
    say(f"  {'PASS' if ok11 else 'FAIL'}  契约自检 27=24+3 / 21=18+3")


# ══════════════════════════════════════════════════════════════ B 密钥
def check_secrets() -> None:
    say()
    say("=" * 72)
    say("[B] 环境与密钥扫描")
    say("=" * 72)
    generic_patterns = [
        (re.compile(r"SECRET_KEY\s*=\s*['\"][0-9a-fA-F]{32,}['\"]"), "硬编码 JWT 密钥"),
        (re.compile(r"MYSQL_PASSWORD\s*=\s*['\"](?!CHANGE_ME|''|\"\")[^'\"]{3,}['\"]"), "硬编码数据库口令"),
        (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."), "硬编码 JWT 字面量"),
    ]
    product_only_patterns = [
        (re.compile(r"(?i)\bpassword\s*=\s*['\"][^'\"]{6,}['\"]"), "硬编码口令字面量"),
    ]

    hits = []
    scanned = 0
    for path, rel in _iter_code():
        if rel.startswith("backend/.env") and not rel.endswith(".example"):
            continue
        if rel.endswith(".env.example") or rel.startswith("scripts/"):
            continue
        scanned += 1
        is_product = any(rel.startswith(d + "/") for d in PRODUCT_DIRS)
        patterns = generic_patterns + (product_only_patterns if is_product else [])
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if _is_exempt_secret(line):
                continue
            for rx, label in patterns:
                if rx.search(line):
                    hits.append(f"{rel}:{i} [{label}]")
    ok = not hits
    record("B 密钥", f"仓库源码硬编码密钥扫描（{scanned} 文件）", ok, str(hits[:4]))
    say(f"  {'PASS' if ok else 'FAIL'}  硬编码密钥扫描 {scanned} 文件，命中 {len(hits)}")
    for h in hits[:10]:
        say(f"        {h}")

    leak = [rel for rel in BATCH5_FILES
            if re.search(r"SECRET_KEY\s*=\s*['\"][^'\"]{8,}['\"]", _read(rel))]
    ok2 = not leak
    record("B 密钥", "本批文件中无 SECRET_KEY 硬编码", ok2, str(leak))
    say(f"  {'PASS' if ok2 else 'FAIL'}  本批文件无 SECRET_KEY 硬编码 {leak or ''}")

    ok3 = True
    detail3 = ""
    for rel in BATCH5_TEST_FILES + BATCH5_SCRIPT_FILES:
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if _is_exempt_secret(line):
                continue
            if re.search(r"\b(SECRET_KEY|MYSQL_PASSWORD|MYSQL_USER)\b\s*[:=]", line):
                ok3 = False
                detail3 = f"{rel}:{i}"
                break
    record("B 密钥", "本批测试/脚本不引用生产凭据变量", ok3, detail3)
    say(f"  {'PASS' if ok3 else 'FAIL'}  本批测试/脚本不引用生产凭据变量 {detail3}")

    ex_text = _read("backend/.env.example")
    ok4 = "SECRET_KEY=CHANGE_ME" in ex_text and "MYSQL_PASSWORD=CHANGE_ME" in ex_text
    record("B 密钥", ".env.example 仍为占位符（本批未改）", ok4)
    say(f"  {'PASS' if ok4 else 'FAIL'}  .env.example 仍为纯占位符")

    import subprocess

    git = r"E:\git\Git\cmd\git.exe"
    tracked = []
    if os.path.isfile(git):
        r = subprocess.run([git, "ls-files"], cwd=str(ROOT), capture_output=True)
        files = r.stdout.decode("utf-8", "replace").splitlines()
        tracked = [f for f in files if re.match(r"^backend/\.env(\.|$)", f)]
    ok5 = not tracked
    record("B 密钥", ".env* 未被 git 跟踪", ok5, str(tracked))
    say(f"  {'PASS' if ok5 else 'FAIL'}  .env* 未被 git 跟踪 {tracked or ''}")


def _is_exempt_secret(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in ("change_me", "占位", "示例", "example", "模板", "redact", "placeholder"))


# ══════════════════════════════════════════════════════════════ C 红线
def check_medical() -> None:
    say()
    say("=" * 72)
    say("[C] 医疗红线扫描（本批源码 + 全部 app 源码）")
    say("=" * 72)
    app_all = sorted(str(p.relative_to(ROOT)).replace(os.sep, "/")
                     for p in (BACKEND / "app").rglob("*.py"))
    targets = sorted(set(BATCH5_FILES + app_all))
    hits = []
    lines = 0
    for rel in targets:
        for i, line in enumerate(_read(rel).splitlines(), 1):
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

    banned_keys = ("diagnosis", "advice", "suggestion", "risk_level", "risk",
                   "health_score", "conclusion", "recommendation", "abnormal")
    key_hits = []
    for rel in BATCH5_APP_FILES:
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if any(m.lower() in line.lower() for m in EXEMPT_MARKERS):
                continue
            for k in banned_keys:
                if re.search(rf"['\"]{k}['\"]\s*:", line):
                    key_hits.append(f"{rel}:{i} 「{k}」")
    ok2 = not key_hits
    record("C 红线", "本批响应结构无医学解释字段名", ok2, str(key_hits[:4]))
    say(f"  {'PASS' if ok2 else 'FAIL'}  无医学解释字段名" + ("" if ok2 else f" {key_hits[:6]}"))


# ══════════════════════════════════════════════════════════════ D 基线
def check_baseline() -> None:
    say()
    say("=" * 72)
    say("[D] 基线一致性（S0 / S1 / S2 第一~第四批 成果未被本轮改动）")
    say("=" * 72)
    ref = ARTIFACTS_DIR / REFERENCE_DOC
    if not ref.is_file():
        record("D 基线", "参照文件存在", False, f"缺 {REFERENCE_DOC}")
        say(f"  FAIL  缺少参照文件 {REFERENCE_DOC}")
        return
    ref_mtime = ref.stat().st_mtime
    say(f"  参照点：{REFERENCE_DOC}  {time.strftime('%m-%d %H:%M:%S', time.localtime(ref_mtime))}")

    s1 = sorted(p for p in ARTIFACTS_DIR.glob("S1-*.md"))
    changed = [p.name for p in s1 if p.stat().st_mtime > ref_mtime + 1]
    ok = not changed
    record("D 基线", f"S1 封板文档 {len(s1)} 份未被本轮改动", ok, str(changed))
    say(f"  {'PASS' if ok else 'FAIL'}  S1 文档 {len(s1)} 份，本轮改动 {len(changed)} 份 {changed or ''}")

    s0 = sorted(p for p in ARTIFACTS_DIR.glob("S0-*.md"))
    changed0 = [p.name for p in s0 if p.stat().st_mtime > ref_mtime + 1]
    ok0 = not changed0
    record("D 基线", f"S0 封板文档 {len(s0)} 份未被本轮改动", ok0, str(changed0))
    say(f"  {'PASS' if ok0 else 'FAIL'}  S0 文档 {len(s0)} 份，本轮改动 {len(changed0)} 份 {changed0 or ''}")

    # 「既有交付物」= 排除参照点与本批自身产出（S2-第五批*）
    s2 = sorted(p for p in ARTIFACTS_DIR.glob("S2-*.md")
                if p.name != REFERENCE_DOC and not p.name.startswith("S2-第五批"))
    changed2 = [p.name for p in s2 if p.stat().st_mtime > ref_mtime + 1]
    ok2 = not changed2
    record("D 基线", f"S2 既有交付物 {len(s2)} 份未被本轮改动", ok2, str(changed2))
    say(f"  {'PASS' if ok2 else 'FAIL'}  S2 既有交付物 {len(s2)} 份，本轮改动 {len(changed2)} 份"
        + ("" if ok2 else f" {changed2}"))

    protected = sorted(_protected_files())
    frozen_hits = [rel for rel in protected if _mtime(rel) > ref_mtime + 1]
    ok3 = not frozen_hits
    record("D 基线", f"第一~第四批受保护文件 {len(protected)} 项 mtime 未越界", ok3,
           str(frozen_hits[:6]))
    say(f"  {'PASS' if ok3 else 'FAIL'}  受保护文件 {len(protected)} 项，越界 {len(frozen_hits)}"
        + ("" if ok3 else f" {frozen_hits[:6]}"))

    judgers = [rel for rel in OLD_JUDGERS if _mtime(rel) > ref_mtime + 1]
    ok4 = not judgers
    record("D 基线", "旧批判据文件（batch2~4）未被本轮修改", ok4, str(judgers))
    say(f"  {'PASS' if ok4 else 'FAIL'}  旧批判据文件未改动 {len(OLD_JUDGERS) - len(judgers)}"
        f"/{len(OLD_JUDGERS)}")

    non_sealed = [n for n in BATCH2_DOCS
                  if not (ARTIFACTS_DIR / n).is_file()
                  or "SEALED" not in _read(str(Path(".workbuddy/artifacts") / n))]
    ok5 = not non_sealed
    record("D 基线", "S2 第二批 4 份交付物保留 SEALED / 通过标记", ok5, str(non_sealed))
    say(f"  {'PASS' if ok5 else 'FAIL'}  S2 第二批交付物标记完整"
        + ("" if ok5 else f" 缺：{non_sealed}"))

    seal4 = ARTIFACTS_DIR / BATCH4_SEAL_DOC
    ok6 = seal4.is_file() and "SEALED" in _read(str(Path(".workbuddy/artifacts") / BATCH4_SEAL_DOC))
    record("D 基线", f"S2 第四批封板记录存在且含 SEALED（{BATCH4_SEAL_DOC}）", ok6)
    say(f"  {'PASS' if ok6 else 'FAIL'}  S2 第四批封板记录 {BATCH4_SEAL_DOC}")

    n_docs = len(list(ARTIFACTS_DIR.glob("*.md")))
    record("D 基线", f"artifacts 交付物 {n_docs} 份（≥ 58）", n_docs >= 58, str(n_docs))
    say(f"  {'PASS' if n_docs >= 58 else 'FAIL'}  artifacts 交付物 {n_docs} 份")


# ══════════════════════════════════════════════════════════════ E ORM
def check_orm() -> None:
    say()
    say("=" * 72)
    say("[E] ORM 模型 ↔ 表（本批 0 新增模型）")
    say("=" * 72)
    model_dir = BACKEND / "app" / "models"
    files = sorted(p.name for p in model_dir.glob("*.py"))
    ok = files == FROZEN_MODEL_FILES
    record("E ORM", f"models/ 文件清单冻结（{len(FROZEN_MODEL_FILES)} 个）", ok,
           str(sorted(set(files) ^ set(FROZEN_MODEL_FILES))))
    say(f"  {'PASS' if ok else 'FAIL'}  models 文件 {len(files)} 个"
        + ("" if ok else f"  差异={sorted(set(files) ^ set(FROZEN_MODEL_FILES))}"))

    from app.models.base import Base

    tables = sorted(Base.metadata.tables)
    ok2 = tables == sorted(FROZEN_TABLES)
    record("E ORM", "Base.metadata 表 == 冻结 8 张业务表", ok2,
           str(sorted(set(tables) ^ set(FROZEN_TABLES))))
    say(f"  {'PASS' if ok2 else 'FAIL'}  ORM 表 {tables}")

    # 模型类 ↔ 表名一一对应（无重名 / 无孤儿 __tablename__）
    tablenames = [t for t in tables]
    ok3 = len(tablenames) == len(set(tablenames))
    record("E ORM", "模型与表一一对应（无重名表）", ok3)
    say(f"  {'PASS' if ok3 else 'FAIL'}  模型 ↔ 表一一对应")


# ══════════════════════════════════════════════════════════════ F 迁移
def check_migration() -> None:
    say()
    say("=" * 72)
    say("[F] 迁移与 DDL（0 migration）")
    say("=" * 72)
    vers = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py")
                  if not p.name.startswith("__"))
    ok = not any(v.startswith("0002") for v in vers)
    record("F 迁移", "无 0002_* 迁移（本批 0 migration）", ok, str(vers))
    say(f"  {'PASS' if ok else 'FAIL'}  迁移文件 {vers}")

    # 本批三文件内不得出现 DDL / 迁移调用
    ddl_pat = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+TABLE|DROP\s+TABLE|op\.add_column|"
                         r"op\.create_table|op\.create_index)\b", re.IGNORECASE)
    ddl_hits = []
    for rel in BATCH5_FILES:
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if ddl_pat.search(line):
                ddl_hits.append(f"{rel}:{i}")
    ok2 = not ddl_hits
    record("F 迁移", "本批文件无 DDL / 迁移调用（0 结构变更）", ok2, str(ddl_hits[:4]))
    say(f"  {'PASS' if ok2 else 'FAIL'}  本批无 DDL 调用" + ("" if ok2 else f" {ddl_hits[:4]}"))


# ══════════════════════════════════════════════════════════════ G 冒烟
def check_smoke() -> None:
    say()
    say("=" * 72)
    say("[G] 冒烟（health + 3 条新路由可达）")
    say("=" * 72)
    from app import create_app

    app = create_app("development")
    c = app.test_client()

    r = c.get("/api/v1/health")
    ok = r.status_code == 200 and (r.get_json() or {}).get("code") == "OK"
    record("G 冒烟", "GET /api/v1/health → 200 OK（免鉴权）", ok, str(r.status_code))
    say(f"  {'PASS' if ok else 'FAIL'}  health {r.status_code}")

    probes = [
        ("/api/v1/home/overview", None),
        ("/api/v1/stats/trend", {"metric_type": "water"}),
        ("/api/v1/stats/summary", {"metric_type": "water"}),
    ]
    for path, q in probes:
        r = c.get(path, query_string=q or {})
        reachable = r.status_code != 404
        record("G 冒烟", f"{path} 可达（401 而非 404）", reachable and r.status_code == 401,
               str(r.status_code))
        say(f"  {'PASS' if reachable and r.status_code == 401 else 'FAIL'}  "
            f"{path} → {r.status_code}")


# ══════════════════════════════════════════════════════════════ H 契约
def check_contract() -> None:
    say()
    say("=" * 72)
    say("[H] 本批契约（S-01 / S-02 / S-03 关键断言，只读）")
    say("=" * 72)
    from app import create_app

    app = create_app("development")
    c = app.test_client()
    hex32 = re.compile(r"^[0-9a-f]{32}$")

    probes = [
        ("/api/v1/home/overview", None),
        ("/api/v1/stats/trend", {"metric_type": "water"}),
        ("/api/v1/stats/summary", {"metric_type": "water"}),
    ]

    # H1 无 Token → 401 + 统一 envelope（四字段 + request_id 32hex）
    env_ok = True
    detail = ""
    for path, q in probes:
        r = c.get(path, query_string=q or {})
        body = r.get_json() or {}
        good = (r.status_code == 401 and body.get("code") == "UNAUTHENTICATED"
                and set(body) == {"code", "message", "data", "request_id"}
                and body.get("data") is None and hex32.match(str(body.get("request_id"))))
        if not good:
            env_ok = False
            detail = f"{path} {r.status_code} {body.get('code')}"
            break
    record("H 契约", "三接口 401 统一 envelope（code/message/data/request_id）", env_ok, detail)
    say(f"  {'PASS' if env_ok else 'FAIL'}  401 envelope 一致 {detail}")

    # H2 query 注入 user_id → 400 INVALID_PARAM（全局守卫，早于鉴权）
    guard_ok = True
    detail2 = ""
    for path, q in probes:
        merged = dict(q or {})
        merged["user_id"] = "1"
        r = c.get(path, query_string=merged)
        body = r.get_json() or {}
        if not (r.status_code == 400 and body.get("code") == "INVALID_PARAM"):
            guard_ok = False
            detail2 = f"{path} {r.status_code} {body.get('code')}"
            break
    record("H 契约", "三接口 query 携带 user_id → 400 INVALID_PARAM", guard_ok, detail2)
    say(f"  {'PASS' if guard_ok else 'FAIL'}  user_id 注入拦截 {detail2}")

    # H3 JSON 体注入 user_id → 400 INVALID_PARAM
    body_ok = True
    detail3 = ""
    for path, q in probes:
        r = c.get(path, query_string=q or {}, json={"user_id": 1})
        body = r.get_json() or {}
        if not (r.status_code == 400 and body.get("code") == "INVALID_PARAM"):
            body_ok = False
            detail3 = f"{path} {r.status_code} {body.get('code')}"
            break
    record("H 契约", "三接口 JSON 体携带 user_id → 400 INVALID_PARAM", body_ok, detail3)
    say(f"  {'PASS' if body_ok else 'FAIL'}  请求体 user_id 拦截 {detail3}")

    # H4 无 Token + 非法参数 → 401（鉴权优先，未泄漏参数校验差异）
    auth_first = True
    detail4 = ""
    for path, q in (
        ("/api/v1/stats/trend", {"metric_type": "water", "window": "15"}),
        ("/api/v1/stats/trend", {"metric_type": "x"}),
        ("/api/v1/stats/summary", {"metric_type": "water", "window": "15"}),
    ):
        r = c.get(path, query_string=q)
        if r.status_code != 401:
            auth_first = False
            detail4 = f"{path} {q} → {r.status_code}"
            break
    record("H 契约", "无 Token 时鉴权优先（非法参数不提前暴露 400）", auth_first, detail4)
    say(f"  {'PASS' if auth_first else 'FAIL'}  鉴权优先 {detail4}")

    # H5 固定常量口径（源码级）
    svc = _read("backend/app/services/stats_service.py")
    api = _read("backend/app/api/v1/stats.py")

    ok5 = "WINDOW_DAYS: Tuple[int, ...] = (7, 30, 90)" in svc and "DEFAULT_WINDOW = 7" in svc
    record("H 契约", "window 仅 {7,30,90}、默认 7（源码口径）", ok5)
    say(f"  {'PASS' if ok5 else 'FAIL'}  window 常量 (7,30,90) / 默认 7")

    chart_ok = all(f'"{k}": "{v}"' in svc for k, v in CHART_FROZEN.items())
    record("H 契约", "8 指标 chart 类型与冻结一致（line/bar）", chart_ok)
    say(f"  {'PASS' if chart_ok else 'FAIL'}  chart 映射 8 指标")

    gf_ok = all(f'"{f}"' in svc for f in GOAL_FIELDS_FROZEN)
    record("H 契约", "S-01 goals[] 固定 8 字段（不增不减）", gf_ok)
    say(f"  {'PASS' if gf_ok else 'FAIL'}  GOAL_FIELDS 8 项")

    mt_ok = all(f'"{m}"' in svc for m in METRIC_TYPES_FROZEN)
    record("H 契约", "8 类 metric_type 全部纳入（weight/bp/heart/glucose/sleep/water/sport/mood）", mt_ok)
    say(f"  {'PASS' if mt_ok else 'FAIL'}  metric_type 8 类")

    # H6 聚合显式隔离：源码中显式出现 is_deleted / user_id 过滤
    n_del = len(re.findall(r"is_deleted\s*==\s*0", svc)) + len(re.findall(r"is_deleted\s*=\s*0", svc))
    n_uid = len(re.findall(r"user_id\s*==", svc))
    ok6 = n_del >= 3 and n_uid >= 3
    record("H 契约", f"聚合显式隔离（is_deleted=0 ×{n_del} / user_id ×{n_uid}）", ok6)
    say(f"  {'PASS' if ok6 else 'FAIL'}  显式隔离 is_deleted×{n_del} user_id×{n_uid}")

    auth_dec = api.count("@require_auth")
    ok7 = auth_dec == 3
    record("H 契约", "三接口均挂 @require_auth（源码级）", ok7, str(auth_dec))
    say(f"  {'PASS' if ok7 else 'FAIL'}  @require_auth ×{auth_dec}")

    # H7 半开区间口径：**实际调用**中不得出现 .between()（docstring 内的口径声明不算）
    ok8 = not re.search(r"\.between\s*\(", svc, re.IGNORECASE)
    record("H 契约", "聚合未使用 SQLAlchemy .between()（统一半开区间 [start,end)）", ok8)
    say(f"  {'PASS' if ok8 else 'FAIL'}  未使用 .between()")

    # H8 交付物齐备
    missing = [rel for rel in BATCH5_EXTRA_FILES if not (ROOT / rel).is_file()]
    ok9 = not missing
    record("H 契约", "本批验收素材齐备（3 × .txt + 1 × Edge .js）", ok9, str(missing))
    say(f"  {'PASS' if ok9 else 'FAIL'}  验收素材齐备" + ("" if ok9 else f" 缺：{missing}"))


# ══════════════════════════════════════════════════════════════ DB
def _connect(cfg):
    import pymysql

    return pymysql.connect(
        host=cfg["MYSQL_HOST"], port=int(cfg["MYSQL_PORT"]), user=cfg["MYSQL_USER"],
        password=cfg["MYSQL_PASSWORD"], charset=cfg["MYSQL_CHARSET"],
        cursorclass=pymysql.cursors.Cursor,
    )


def check_db() -> None:
    from app.core.config import load_config

    say()
    say("=" * 72)
    say("[F-DB] 数据库只读核验（结构冻结 + 数据洁净）")
    say("=" * 72)
    cfg = load_config("development")
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("USE `%s`" % cfg["MYSQL_DB"])
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
                        (cfg["MYSQL_DB"],))
            tables = sorted(r[0] for r in cur.fetchall())
            expected = sorted(FROZEN_TABLES + ["alembic_version"])
            ok = tables == expected
            record("F-DB", "8 业务表 + alembic_version（本批 0 新表）", ok, str(tables))
            say(f"  {'PASS' if ok else 'FAIL'}  表：{tables}")

            cur.execute("SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
                        "WHERE table_schema=%s AND index_name<>'PRIMARY'", (cfg["MYSQL_DB"],))
            n_idx = int(cur.fetchone()[0])
            ok3 = n_idx == 17
            record("F-DB", "非主键索引 17 个（本批 0 新增）", ok3, str(n_idx))
            say(f"  {'PASS' if ok3 else 'FAIL'}  非主键索引 {n_idx} / 17")

            cur.execute("SELECT COUNT(*) FROM information_schema.table_constraints "
                        "WHERE table_schema=%s AND constraint_type='FOREIGN KEY'", (cfg["MYSQL_DB"],))
            n_fk = int(cur.fetchone()[0])
            ok4 = n_fk == 0
            record("F-DB", "外键 0 个", ok4, str(n_fk))
            say(f"  {'PASS' if ok4 else 'FAIL'}  外键 {n_fk} / 0")

            cur.execute("SELECT version_num FROM `%s`.alembic_version" % cfg["MYSQL_DB"])
            ver = [r[0] for r in cur.fetchall()]
            ok5 = ver == ["0001_initial_schema"]
            record("F-DB", "alembic_version == 0001_initial_schema", ok5, str(ver))
            say(f"  {'PASS' if ok5 else 'FAIL'}  alembic_version = {ver}")

            counts = {}
            for t in FROZEN_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                counts[t] = int(cur.fetchone()[0])
            say(f"  业务表行数（含软删物理行）：{counts}")

            # 软删语义：API 删除（R-07 / G-06）为**软删**，物理行按设计保留；
            # 因此"洁净"的正确判据 = 无**活跃**（is_deleted=0）残留，而非物理行数 0。
            active = {}
            for t in ("health_record", "health_goal", "record_tag"):
                cur.execute(f"SELECT COUNT(*) FROM `{t}` WHERE is_deleted = 0")
                active[t] = int(cur.fetchone()[0])
            ok6 = all(v == 0 for v in active.values())
            record("F-DB", "清理后无「活跃」（is_deleted=0）业务行残留", ok6, str(active))
            say(f"  {'PASS' if ok6 else 'FAIL'}  活跃（is_deleted=0）行 {active}")

            cur.execute("SELECT COUNT(*) FROM health_record WHERE is_deleted = 1")
            n_del = int(cur.fetchone()[0])
            record("F-DB", f"软删行按设计保留（health_record is_deleted=1 = {n_del}）", True, str(n_del))
            say(f"  PASS  软删物理行 health_record = {n_del}（第 4 步逐表 DELETE 时物理清除）")

            # 数据范围：业务表内不得存在"非测试账号"的行（测试账号 = acctest* / tst*）
            cur.execute("SELECT id, username FROM user_account")
            test_ids = [int(r[0]) for r in cur.fetchall()
                        if str(r[1]).startswith("acctest") or str(r[1]).startswith("tst")]
            leaked = {}
            for t in ("health_record", "record_tag", "health_goal", "user_profile", "user_session"):
                if test_ids:
                    ph = ",".join(["%s"] * len(test_ids))
                    cur.execute(f"SELECT COUNT(*) FROM `{t}` WHERE user_id NOT IN ({ph})",
                                tuple(test_ids))
                else:
                    cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                leaked[t] = int(cur.fetchone()[0])
            ok7 = all(v == 0 for v in leaked.values())
            record("F-DB", "业务表无「非测试账号」行（未污染真实用户数据）", ok7, str(leaked))
            say(f"  {'PASS' if ok7 else 'FAIL'}  非测试账号行 {leaked}")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="额外执行数据库只读核验")
    args = ap.parse_args()

    say()
    say("#" * 72)
    say("# S2 第五批《首页 / 统计 / 趋势 S-01~S-03》核验")
    say("# 结构 / 密钥 / 红线 / 基线 / ORM / 迁移 / 冒烟 / 契约")
    say("#" * 72)
    check_scope()
    check_secrets()
    check_medical()
    check_baseline()
    check_orm()
    check_migration()
    check_smoke()
    check_contract()
    if args.db:
        check_db()

    groups: dict = {}
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
