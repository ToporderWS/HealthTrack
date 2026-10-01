# -*- coding: utf-8 -*-
"""S2 第四批 —— 范围守卫 / 密钥扫描 / 医疗红线 / 基线一致性 / 数据库 一键核验（只读）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch4.py
    backend\\.venv\\Scripts\\python.exe scripts\\verify_s2_batch4.py --db   # 连库额外核验

覆盖：
- [A] **范围守卫**：接口集合恰为 Y-01 + A-01~A-06 + P-01/P-02 + R-01~R-08 + G-01~G-07
      （**24 条接口 / 18 条路径**）；8 表 / 17 非主键索引 / 0 外键 / 0 提醒表；迁移仅 0001；
      前端页面数不变；S / E / D / A-07 / P1 / P2 与超出 S0 冻结编号的功能零体现；
      错误码仍 18、字段级码仍 7（**未扩充**）
- [B] **密钥与敏感信息**：仓库无硬编码密钥 / 无 `.env` 入库
- [C] **医疗红线**：本批源码 + 全 app 源码（含运行期文案）
- [D] **基线一致性**：S1 / S2 第一批 / 第二批 / 第三批 的封板代码、测试、脚本与文档
      **未被本轮改动**（按 mtime 逐文件判定，排除本批自身产出）
- [E] **数据洁净**：8 张业务表行数与预期一致、结构冻结
- [F] **P-1 同类（D-G1）结构性证据**：第三批 17 条接口**全部保留**，Δ **恰为本批 7 条**，
      第三批判据文件**未被修改** ⇒ 第三批脚本的 7 项 FAIL 属**历史时点判据**（非业务回归）
- [G] **residual**：本批测试结束后 8 张业务表行数合计 0（无测试数据残留）

────────── 与开工方案的两处事实纠正（本文件即纠正载体） ──────────

1. **路径数 13 → 18（不是 19）**：开工方案 §八按"13 + 6"推断 19 条路径，实测为 18。
   G-01~G-07 共 **7 个接口**只映射到 **5 条路径**（``/goals`` 承载 GET+POST；
   ``/goals/<int:goal_id>`` 承载 PATCH+DELETE；``progress`` / ``pause`` / ``resume`` 各 1）。
   接口数 24 = 17 + 7 与冻结契约**完全一致**。

2. **第三批脚本的 FAIL 数为 7（不是 2）**：除「路径 == 13」「接口 == 17」外，还包括
   第三批时点的「本批新增恰 10 个接口」「G/S/E/D 接口零实现」「S2 既有交付物未改」
   「Δ 为纯新增（相对第二批）」「结论」共 5 项 —— 同属**历史时点判据**（P-1 同类）。
   **本脚本不改动第三批任何成果**，并在 [F] 中给出结构性证据。

口径说明（P-1）：第二批判据文件（``verify_s2_batch2.py`` / ``test_medical_redline.py``）
与第三批判据文件（``verify_s2_batch3.py`` / ``tests/batch3/test_batch3_scope_guard.py``）
把接口集合**硬编码为各自批次时点**。后续批次新增合法接口后必然 FAIL。
本脚本**不改动**任何旧批成果，而是以「当前阶段允许集合」独立判定。
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

#: 第四批开工参照点（本批任何改动都应晚于此文件；同时是该文件的创建载体）
REFERENCE_DOC = "S2-第四批-G-01至G-07-开工前实施方案.md"
#: 参照点所在的交付物目录
ARTIFACTS_DIR = ROOT / ".workbuddy" / "artifacts"

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
#: 本批（第四批）新增路径（**5 条**）
BATCH4_NEW_PATHS = {
    "/api/v1/goals",
    "/api/v1/goals/progress",
    "/api/v1/goals/<int:goal_id>",
    "/api/v1/goals/<int:goal_id>/pause",
    "/api/v1/goals/<int:goal_id>/resume",
}
#: 第三批完成时点的允许集合（**17 条接口 / 13 条路径**）
BATCH3_ENDPOINTS = {
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
}
BATCH3_PATHS = BATCH2_PATHS | BATCH3_NEW_PATHS

#: 本批新增接口（7 条）
BATCH4_NEW_ENDPOINTS = {
    ("GET", "/api/v1/goals"),
    ("POST", "/api/v1/goals"),
    ("GET", "/api/v1/goals/progress"),
    ("PATCH", "/api/v1/goals/<int:goal_id>"),
    ("DELETE", "/api/v1/goals/<int:goal_id>"),
    ("POST", "/api/v1/goals/<int:goal_id>/pause"),
    ("POST", "/api/v1/goals/<int:goal_id>/resume"),
}
#: 当前阶段允许的路由集合（路径 **18** 条）
EXPECTED_PATHS = BATCH3_PATHS | BATCH4_NEW_PATHS
#: 当前阶段允许的路由集合（method + 路径，**24** 条）
EXPECTED_ENDPOINTS = BATCH3_ENDPOINTS | BATCH4_NEW_ENDPOINTS

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

#: 本批新增 / 修改的生产代码
BATCH4_APP_FILES = [
    "backend/app/__init__.py",
    "backend/app/schemas/base.py",
    "backend/app/schemas/goal.py",
    "backend/app/services/goal_service.py",
    "backend/app/services/goal_progress.py",
    "backend/app/api/v1/goals.py",
]
#: 本批新增的测试
BATCH4_TEST_FILES = [
    "backend/tests/batch4/__init__.py",
    "backend/tests/batch4/conftest.py",
    "backend/tests/batch4/test_g01_list.py",
    "backend/tests/batch4/test_g02_create.py",
    "backend/tests/batch4/test_g03_patch.py",
    "backend/tests/batch4/test_g04_g06_state.py",
    "backend/tests/batch4/test_g07_progress.py",
    "backend/tests/batch4/test_batch4_scope_guard.py",
    "backend/tests/batch4/test_batch4_contract_isolation.py",
]
#: 本批新增的脚本
BATCH4_SCRIPT_FILES = [
    "scripts/verify_s2_batch4.py",
    "scripts/s2_batch4_http_smoke.py",
]
BATCH4_FILES = BATCH4_APP_FILES + BATCH4_TEST_FILES + BATCH4_SCRIPT_FILES

#: 旧批判据文件（**本轮不得修改**；其 FAIL 属历史时点判据）
OLD_JUDGERS = [
    "scripts/verify_s2_batch2.py",
    "scripts/verify_s2_batch3.py",
    "backend/tests/test_medical_redline.py",
    "backend/tests/batch3/test_batch3_scope_guard.py",
]

#: S2 第二批 4 份交付物
BATCH2_DOCS = [
    "S2-第二批-开工前检查报告.md",
    "S2-第二批开发完成报告.md",
    "S2-第二批-验收通过与封板记录.md",
    "S2-第三批-开工前接管与预检报告.md",
]

BANNED_TERMS = ["诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药", "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围", "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数"]  # noqa: E501  红线声明行
EXEMPT_MARKERS = ["禁止", "不得", "不含", "不涉及", "非医疗", "非医学", "中性", "无医学", "不做", "严禁", "banned", "禁用", "红线", "豁免"]  # noqa: E501  红线声明行

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".hbuilderx",
             "unpackage", "dist", ".workbuddy", ".pytest_cache", "logs", "storage"}
CODE_SUFFIX = (".py", ".js", ".vue", ".json", ".sql", ".ini", ".conf", ".cfg")
PRODUCT_DIRS = ("backend/app", "backend/tests", "frontend", "database")

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


def _protected_files():
    """第一～第三批受保护文件（排除本批新增 / 本批允许修改的 6 个生产文件）。"""
    allowed = set(BATCH4_FILES)
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


# ══════════════════════════════════════════════════════════════ A 范围守卫
def check_scope() -> None:
    say("=" * 72)
    say("[A] 范围守卫（接口 / 错误码 / 迁移 / 前端 / 编号）")
    say("=" * 72)
    from app import create_app

    app = create_app("development")
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = set()
    for r in rules:
        for m in (r.methods or set()) - {"HEAD", "OPTIONS"}:
            endpoints.add((m, str(r)))

    ok = paths == EXPECTED_PATHS
    record("A 范围", "路由路径集合 == 18 条（第二批 7 + 第三批 6 + 本批 5）", ok,
           str(sorted(paths ^ EXPECTED_PATHS)))
    say(f"  {'PASS' if ok else 'FAIL'}  路由路径 {len(paths)} 条 / 目标 18"
        + ("" if ok else f"  差异={sorted(paths ^ EXPECTED_PATHS)}"))

    ok2 = endpoints == EXPECTED_ENDPOINTS
    record("A 范围", "接口（method+路径）集合 == 24 条", ok2,
           str(sorted(endpoints ^ EXPECTED_ENDPOINTS)))
    say(f"  {'PASS' if ok2 else 'FAIL'}  接口 {len(endpoints)} 条 / 目标 24（累计 24/34）"
        + ("" if ok2 else f"  差异={sorted(endpoints ^ EXPECTED_ENDPOINTS)}"))

    new_eps = endpoints - BATCH3_ENDPOINTS
    ok3 = new_eps == BATCH4_NEW_ENDPOINTS
    record("A 范围", "本批新增恰 7 个接口（G-01~G-07）", ok3, str(sorted(new_eps)))
    say(f"  {'PASS' if ok3 else 'FAIL'}  本批新增接口 {len(new_eps)} 个 / 目标 7")

    ok4 = not any(str(r) == "/api/v1/users/me" and "DELETE" in (r.methods or set()) for r in rules)
    record("A 范围", "A-07 注销接口零实现", ok4)
    say(f"  {'PASS' if ok4 else 'FAIL'}  A-07 注销接口零实现")

    forbidden = ("/api/v1/stats", "/api/v1/export", "/api/v1/data", "/api/v1/reminders",
                 "/api/v1/admin", "/api/v1/payments", "/api/v1/home")
    bad = sorted(p for p in paths for f in forbidden if p.startswith(f))
    ok5 = not bad
    record("A 范围", "S / E / D / 提醒 / 管理 / 支付 接口零实现", ok5, str(bad))
    say(f"  {'PASS' if ok5 else 'FAIL'}  越界模块接口零实现" + ("" if ok5 else f" {bad}"))

    from app.core.errors import ERROR_HTTP_STATUS, ERROR_MESSAGE, ErrorCode, FieldErrorCode

    declared = {n for n, v in vars(ErrorCode).items() if not n.startswith("_") and isinstance(v, str)}
    ok6 = declared == FROZEN_CODES == set(ERROR_HTTP_STATUS) == set(ERROR_MESSAGE)
    record("A 范围", "全局错误码集合 == 冻结 18 个（本批未增改）", ok6,
           str(sorted(declared ^ FROZEN_CODES)))
    say(f"  {'PASS' if ok6 else 'FAIL'}  全局错误码仍为冻结 18 个")

    fc = {n for n, v in vars(FieldErrorCode).items() if not n.startswith("_") and isinstance(v, str)}
    ok7 = fc == FROZEN_FIELD_CODES
    record("A 范围", "字段级码 == 冻结 7 个（软提示走独立 warnings[]）", ok7,
           str(sorted(fc ^ FROZEN_FIELD_CODES)))
    say(f"  {'PASS' if ok7 else 'FAIL'}  字段级码仍为冻结 7 个")

    from app.core.warnings import WarningCode  # noqa: F401

    ok8 = set(vars(WarningCode)) >= {"OUT_OF_COMMON_RANGE"}
    record("A 范围", "软提示码独立存在（WarningCode.OUT_OF_COMMON_RANGE）", ok8)
    say(f"  {'PASS' if ok8 else 'FAIL'}  软提示独立码 OUT_OF_COMMON_RANGE")

    vers = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py")
                  if not p.name.startswith("__"))
    ok9 = vers == ["0001_initial_schema.py"]
    record("A 范围", "迁移仅 0001_initial_schema（0 migration）", ok9, str(vers))
    say(f"  {'PASS' if ok9 else 'FAIL'}  迁移文件 {vers}")

    pages = sorted(str(p.relative_to(ROOT / "frontend")).replace(os.sep, "/")
                   for p in (ROOT / "frontend" / "pages").rglob("*.vue"))
    ok10 = pages == ["pages/index/index.vue"]
    record("A 范围", "前端仍仅 1 个占位页（本批不改业务页面）", ok10, str(pages))
    say(f"  {'PASS' if ok10 else 'FAIL'}  前端页面 {pages}")

    bad_ids = []
    for path, rel in _iter_code(only_dirs=PRODUCT_DIRS):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"F-0(\d{2})\b", text):
            if int(m.group(1)) >= 89:
                bad_ids.append(f"{rel}:F-{m.group(1)}")
    ok11 = not bad_ids
    record("A 范围", "超出 S0 冻结编号的功能零体现（源码/注释）", ok11, str(bad_ids[:5]))
    say(f"  {'PASS' if ok11 else 'FAIL'}  越界功能编号零体现"
        + ("" if ok11 else f" {bad_ids[:5]}"))

    ok12 = (len(EXPECTED_ENDPOINTS) == 24 and len(EXPECTED_PATHS) == 18
            and len(BATCH3_ENDPOINTS) == 17 and len(BATCH4_NEW_ENDPOINTS) == 7)
    record("A 范围", "契约自检：24 接口 = 17（第三批）+ 7（本批）；18 路径 = 13 + 5", ok12)
    say(f"  {'PASS' if ok12 else 'FAIL'}  契约自检 24=17+7 / 18=13+5")


# ══════════════════════════════════════════════════════════════ B 密钥扫描
def check_secrets() -> None:
    say()
    say("=" * 72)
    say("[B] 密钥与敏感信息扫描")
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

    leak = []
    for rel in BATCH4_FILES:
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"SECRET_KEY\s*=\s*['\"][^'\"]{8,}['\"]", text):
            leak.append(rel)
    ok2 = not leak
    record("B 密钥", "本批文件中无 SECRET_KEY 硬编码", ok2, str(leak))
    say(f"  {'PASS' if ok2 else 'FAIL'}  本批文件无 SECRET_KEY 硬编码 {leak or ''}")

    ok3 = True
    detail3 = ""
    for rel in BATCH4_TEST_FILES + BATCH4_SCRIPT_FILES:
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if _is_exempt_secret(line):
                continue                     # 占位符 / 示例 / 说明行不视为"引用生产凭据"
            if re.search(r"\b(SECRET_KEY|MYSQL_PASSWORD|MYSQL_USER)\b\s*[:=]", line):
                ok3 = False
                detail3 = f"{rel}:{i}"
                break
    record("B 密钥", "本批测试/脚本不引用生产凭据变量", ok3, detail3)
    say(f"  {'PASS' if ok3 else 'FAIL'}  本批测试/脚本不引用生产凭据变量 {detail3}")

    ex = BACKEND / ".env.example"
    text = ex.read_text(encoding="utf-8", errors="ignore") if ex.is_file() else ""
    ok4 = "SECRET_KEY=CHANGE_ME" in text and "MYSQL_PASSWORD=CHANGE_ME" in text
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


# ══════════════════════════════════════════════════════════════ C 医疗红线
def check_medical() -> None:
    say()
    say("=" * 72)
    say("[C] 医疗红线扫描（本批源码 + 全部 app 源码）")
    say("=" * 72)
    app_all = sorted(str(p.relative_to(ROOT)).replace(os.sep, "/")
                     for p in (BACKEND / "app").rglob("*.py"))
    targets = sorted(set(BATCH4_FILES + app_all))
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

    banned_keys = ("diagnosis", "advice", "suggestion", "risk_level", "risk",
                   "health_score", "conclusion", "recommendation", "abnormal")
    key_hits = []
    for rel in BATCH4_APP_FILES:
        path = ROOT / rel
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(m.lower() in line.lower() for m in EXEMPT_MARKERS):
                continue
            for k in banned_keys:
                if re.search(rf"['\"]{k}['\"]\s*:", line):
                    key_hits.append(f"{rel}:{i} 「{k}」")
    ok2 = not key_hits
    record("C 红线", "本批响应结构无医学解释字段名", ok2, str(key_hits[:4]))
    say(f"  {'PASS' if ok2 else 'FAIL'}  无医学解释字段名" + ("" if ok2 else f" {key_hits[:6]}"))


# ══════════════════════════════════════════════════════════════ D 基线一致性
def check_baseline() -> None:
    say()
    say("=" * 72)
    say("[D] 基线一致性（S1 / S2 第一~第三批 成果未被本轮改动）")
    say("=" * 72)
    ref = ARTIFACTS_DIR / REFERENCE_DOC
    if not ref.is_file():
        record("D 基线", "参照文件存在", False, f"缺 {REFERENCE_DOC}")
        say(f"  FAIL  缺少参照文件 {REFERENCE_DOC}")
        return
    ref_mtime = ref.stat().st_mtime
    say(f"  参照点：{REFERENCE_DOC}  "
        f"{time.strftime('%m-%d %H:%M:%S', time.localtime(ref_mtime))}")

    s1 = sorted(p for p in ARTIFACTS_DIR.glob("S1-*.md"))
    changed = [p.name for p in s1 if p.stat().st_mtime > ref_mtime + 1]
    ok = not changed
    record("D 基线", f"S1 封板文档 {len(s1)} 份未被本轮改动", ok, str(changed))
    say(f"  {'PASS' if ok else 'FAIL'}  S1 文档 {len(s1)} 份，本轮改动 {len(changed)} 份 {changed or ''}")

    # 「既有交付物」= 排除参照点与本批自身产出（S2-第四批*）
    s2 = sorted(p for p in ARTIFACTS_DIR.glob("S2-*.md")
                if p.name != REFERENCE_DOC and not p.name.startswith("S2-第四批"))
    changed2 = [p.name for p in s2 if p.stat().st_mtime > ref_mtime + 1]
    ok2 = not changed2
    record("D 基线", f"S2 既有交付物 {len(s2)} 份未被本轮改动", ok2, str(changed2))
    say(f"  {'PASS' if ok2 else 'FAIL'}  S2 既有交付物 {len(s2)} 份，本轮改动 {len(changed2)} 份"
        + ("" if ok2 else f" {changed2}"))

    protected = sorted(_protected_files())
    frozen_hits = [rel for rel in protected if _mtime(rel) > ref_mtime + 1]
    ok3 = not frozen_hits
    record("D 基线", f"第一～第三批受保护文件 {len(protected)} 项 mtime 未越界", ok3,
           str(frozen_hits[:6]))
    say(f"  {'PASS' if ok3 else 'FAIL'}  受保护文件 {len(protected)} 项，越界 {len(frozen_hits)}"
        + ("" if ok3 else f" {frozen_hits[:6]}"))

    judgers = [rel for rel in OLD_JUDGERS if _mtime(rel) > ref_mtime + 1]
    ok4 = not judgers
    record("D 基线", "旧批判据文件（batch2/batch3）未被本轮修改", ok4, str(judgers))
    say(f"  {'PASS' if ok4 else 'FAIL'}  旧批判据文件未改动 {len(OLD_JUDGERS) - len(judgers)}"
        f"/{len(OLD_JUDGERS)}")

    non_sealed = [n for n in BATCH2_DOCS
                  if not (ARTIFACTS_DIR / n).is_file()
                  or "SEALED" not in (ARTIFACTS_DIR / n).read_text(encoding="utf-8", errors="ignore")]
    ok5 = not non_sealed
    record("D 基线", "S2 第二批 4 份交付物保留 SEALED / 通过标记", ok5, str(non_sealed))
    say(f"  {'PASS' if ok5 else 'FAIL'}  S2 第二批交付物标记完整"
        + ("" if ok5 else f" 缺：{non_sealed}"))

    n_docs = len(list(ARTIFACTS_DIR.glob("*.md")))
    record("D 基线", f"artifacts 交付物 {n_docs} 份（≥ 47）", n_docs >= 47, str(n_docs))
    say(f"  {'PASS' if n_docs >= 47 else 'FAIL'}  artifacts 交付物 {n_docs} 份")


# ══════════════════════════════════════════════════════════════ E 数据库
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
    say("[E] 数据库只读核验（结构冻结 + 数据洁净）")
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
            record("E DB", "8 业务表 + alembic_version（本批 0 新表）", ok, str(tables))
            say(f"  {'PASS' if ok else 'FAIL'}  表：{tables}")

            ok2 = "reminder" not in " ".join(tables).lower()
            record("E DB", "无 reminder 相关表", ok2)
            say(f"  {'PASS' if ok2 else 'FAIL'}  无 reminder 表")

            cur.execute("SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
                        "WHERE table_schema=%s AND index_name<>'PRIMARY'", (cfg["MYSQL_DB"],))
            n_idx = int(cur.fetchone()[0])
            ok3 = n_idx == 17
            record("E DB", "非主键索引 17 个（本批 0 新增）", ok3, str(n_idx))
            say(f"  {'PASS' if ok3 else 'FAIL'}  非主键索引 {n_idx} / 17")

            cur.execute("SELECT COUNT(*) FROM information_schema.table_constraints "
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


# ══════════════════════════════════════════════════════════════ F P-1 同类
def check_p1() -> None:
    say()
    say("=" * 72)
    say("[F] P-1 同类（D-G1）结构性证据：第三批 17 条接口全保留 + Δ 恰为本批 7 条")
    say("=" * 72)
    from app import create_app

    app = create_app("development")
    paths = {str(r) for r in app.url_map.iter_rules() if str(r).startswith("/api/")}
    endpoints = {(m, str(r)) for r in app.url_map.iter_rules() if str(r).startswith("/api/")
                 for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}

    superset = BATCH3_ENDPOINTS <= endpoints
    record("F P-1", "第三批 17 条接口全部保留（未删除任何既有接口）", superset,
           str(sorted(BATCH3_ENDPOINTS - endpoints)))
    say(f"  {'PASS' if superset else 'FAIL'}  第三批 17 条接口 ⊆ 当前 {len(endpoints)} 条")

    delta = endpoints - BATCH3_ENDPOINTS
    pure_add = delta == BATCH4_NEW_ENDPOINTS
    record("F P-1", "Δ 恰为本批 7 条新接口（无 G 之外新增）", pure_add, str(sorted(delta)))
    say(f"  {'PASS' if pure_add else 'FAIL'}  Δ = {sorted(delta)}")

    path_delta = paths - BATCH3_PATHS
    ok_path = path_delta == BATCH4_NEW_PATHS
    record("F P-1", "路径 Δ 恰为本批 5 条新路径（13 → 18）", ok_path, str(sorted(path_delta)))
    say(f"  {'PASS' if ok_path else 'FAIL'}  路径 Δ = {sorted(path_delta)}")

    no_removal = not (BATCH3_ENDPOINTS - endpoints) and not (BATCH3_PATHS - paths)
    record("F P-1", "无任何既有接口 / 路径被移除 / 改名", no_removal)
    say(f"  {'PASS' if no_removal else 'FAIL'}  既有接口移除数 0")

    ref = ARTIFACTS_DIR / REFERENCE_DOC
    ref_mtime = ref.stat().st_mtime if ref.is_file() else 0.0
    untouched = [rel for rel in OLD_JUDGERS if _mtime(rel) <= ref_mtime + 1]
    ok4 = len(untouched) == len(OLD_JUDGERS)
    record("F P-1", "旧批范围判据文件未被本批修改", ok4,
           str(sorted(set(OLD_JUDGERS) - set(untouched))))
    say(f"  {'PASS' if ok4 else 'FAIL'}  旧批判据文件未改动 {len(untouched)}/{len(OLD_JUDGERS)}")

    ok5 = ok4 and pure_add and superset and no_removal and ok_path
    record("F P-1", "结论：第三批脚本 7 项 FAIL 属历史时点判据（非业务回归）", ok5)
    say("  说明：第三批脚本/测试把接口集合硬编码为**第三批时点**（17 条 / 13 路径）")
    say("        与其自述的「G 模块零实现」；第四批新增合法接口后必然 FAIL。")
    say("        本批已用「第三批接口全保留 + Δ 恰为 7 条 + 判据文件未改」证明其为误报。")


# ══════════════════════════════════════════════════════════════ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="额外执行数据库只读核验")
    args = ap.parse_args()

    say()
    say("#" * 72)
    say("# S2 第四批《健康目标 G-01~G-07》核验")
    say("# 范围守卫 / 密钥 / 红线 / 基线 / 数据洁净 / P-1 同类结构性证据")
    say("#" * 72)
    check_scope()
    check_secrets()
    check_medical()
    check_baseline()
    check_p1()
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
