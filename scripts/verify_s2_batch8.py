# -*- coding: utf-8 -*-
"""S2 第八批 A-07（注销账号）—— 本批**唯一**回归判定脚本（A~H 八段）。

用法：
- ``python scripts/verify_s2_batch8.py``          只读静态核验（默认）
- ``python scripts/verify_s2_batch8.py --db``     追加**只读**连库核验（F-DB 段）

约定：
- **只读**：不写库、不改文件、不执行 DDL；
- 输出可落盘复用（``> .workbuddy/_b8verify.txt``），**不使用**任何管道；
- 历史批次（batch5 / batch6 / batch7）守卫脚本把它们**当时**的接口集合硬编码，
  且 batch7 含"**A-07 未注册**"判据；本批实现 A-07 后必然 FAIL ——
  属**历史时点判据**，处置 = **零改动 + 显式豁免**（见实现报告与封板记录）；
  **本批权威判定只看本脚本**。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
ARTIFACTS = PROJECT / ".workbuddy" / "artifacts"
SCRIPTS = PROJECT / "scripts"

#: 基线参照点：S2 第七批封板记录（batch8 之前最后一枚"时点印章"）
REFERENCE_DOC = ARTIFACTS / "S2-第七批-D01至D02-验收通过与封板记录.md"

#: **本批开工点**：Step 0 只读预检报告（batch8 第一件产物）。
#: ``[D]`` 段以**本批开工点**为界，避免把之后本批新增报告误判为"既有交付物被改动"。
START_DOC = ARTIFACTS / "S2-第八批-A07-开工前只读预检报告.md"

#: 本批新增 / 修改的生产代码（相对 backend/）
BATCH8_FILES = (
    "app/__init__.py",
    "app/services/account_service.py",
    "app/api/v1/account.py",
)

#: 本批新增的交付物（不属于"受保护文件"）
BATCH8_OWN = {
    "backend/tests/batch8",
    "backend/app/__init__.py",
    "backend/app/services/account_service.py",
    "backend/app/api/v1/account.py",
    "scripts/verify_s2_batch8.py",
    "scripts/s2_batch8_http_smoke.py",
    "scripts/b8_cleanup_testdata.py",
    "scripts/s2_batch8_accept.console.txt",
    "scripts/s2_batch8_accept.cmd.txt",
    "scripts/s2_batch8_accept.sql.txt",
    "S2_第八批_A07_Edge验收脚本.js",
}

#: 本批新建的文档（不参与"已封板成果未改动"判定）
BATCH8_DOCS = {
    "S2-第八批-A07-开工前只读预检报告.md",
    "S2-第八批-A07-Step1实现报告.md",
    "S2-第八批-A07-环境残留清理与最终复核报告.md",
    "S2-第八批-A07-验收通过与封板记录.md",
}

FROZEN_TABLES = ["user_account", "user_profile", "health_record", "record_tag",
                 "health_goal", "user_session", "login_failure_state", "export_job"]
MIGRATION_TABLE = "alembic_version"
EXPECTED_TABLE_COUNT = 9

FROZEN_CODES = {
    "INVALID_PARAM", "UNAUTHENTICATED", "CREDENTIALS_INVALID", "TOKEN_REUSED",
    "RESOURCE_NOT_FOUND", "USERNAME_TAKEN", "GOAL_TYPE_EXISTS", "EXPORT_IN_PROGRESS",
    "IDEMPOTENCY_CONFLICT", "COUNT_MISMATCH", "EXPORT_EXPIRED", "VALIDATION_FAILED",
    "PASSWORD_INVALID", "ACCOUNT_LOCKED", "SESSION_VERIFY_ABORTED", "SOFT_WARNING",
    "INTERNAL_ERROR", "SERVICE_UNAVAILABLE",
}
FROZEN_FIELD_CODES = {"REQUIRED", "INVALID_TYPE", "INVALID_FORMAT", "WEAK_PASSWORD",
                      "MISMATCH", "SAME_AS_OLD", "NOT_ACCEPTED"}

#: 本批新增（1 条接口 / **0 条新路径** —— A-07 复用既有 ``/api/v1/users/me``）
BATCH8_ENDPOINTS = {("DELETE", "/api/v1/users/me")}
BATCH8_PATHS = {"/api/v1/users/me"}
EXPECTED_ENDPOINTS_COUNT = 34
EXPECTED_PATHS_COUNT = 26

#: S2 第七批封板时的 33 条接口（本批必须全部保留）
BATCH7_ENDPOINTS = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"), ("POST", "/api/v1/auth/logout"),
    ("PUT", "/api/v1/auth/password"),
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/profile"), ("PUT", "/api/v1/profile"),
    ("POST", "/api/v1/records"), ("GET", "/api/v1/records"),
    ("GET", "/api/v1/records/count"), ("GET", "/api/v1/records/options"),
    ("GET", "/api/v1/records/<int:record_id>"),
    ("PATCH", "/api/v1/records/<int:record_id>"),
    ("DELETE", "/api/v1/records/<int:record_id>"),
    ("POST", "/api/v1/records/batch-delete"),
    ("POST", "/api/v1/goals"), ("GET", "/api/v1/goals"),
    ("PATCH", "/api/v1/goals/<int:goal_id>"), ("DELETE", "/api/v1/goals/<int:goal_id>"),
    ("POST", "/api/v1/goals/<int:goal_id>/pause"),
    ("POST", "/api/v1/goals/<int:goal_id>/resume"),
    ("GET", "/api/v1/goals/progress"),
    ("GET", "/api/v1/home/overview"),
    ("GET", "/api/v1/stats/trend"), ("GET", "/api/v1/stats/summary"),
    ("POST", "/api/v1/exports"), ("GET", "/api/v1/exports"),
    ("GET", "/api/v1/exports/<int:export_id>"),
    ("GET", "/api/v1/exports/<int:export_id>/download"),
    ("GET", "/api/v1/me/data/summary"), ("POST", "/api/v1/me/data/clear"),
}

#: A-07 冻结的 8 步物理删除顺序
DELETE_ORDER = ("record_tag", "health_record", "health_goal", "user_profile",
                "export_job", "user_session", "login_failure_state", "user_account")

BANNED_TERMS = ("诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药",
                "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围",
                "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数")
EXEMPT_MARKERS = ("禁止", "不得", "不含", "不涉及", "非医疗", "非医学", "中性", "无医学",
                  "不做", "严禁", "banned", "禁用", "红线", "豁免")

results: List[dict] = []
lines: List[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    lines.append(text)


def record(section: str, name: str, ok: bool, detail: str = "") -> None:
    results.append({"section": section, "name": name, "ok": bool(ok), "detail": detail})
    say(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail and not ok else ""))


def _read(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8")


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.is_file() else 0.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _own(rel_posix: str) -> bool:
    return any(rel_posix == o or rel_posix.startswith(o + "/") for o in BATCH8_OWN)


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in EXEMPT_MARKERS)


def _class_block(text: str, name: str) -> str:
    match = re.search(r"^class %s\b[\s\S]*?(?=^class |\Z)" % re.escape(name), text, re.M)
    return match.group(0) if match else ""


def _create_table_block(text: str, table: str) -> str:
    match = re.search(r'create_table\(\s*\n?\s*"%s"' % re.escape(table), text)
    if not match:
        return ""
    start = text.find("(", match.start())
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return ""


def _func_body(text: str, name: str) -> str:
    """取顶层函数 ``name`` 的正文（到下一个顶层 ``def`` / 顶层赋值 / 文末）。"""
    match = re.search(r"^def %s\(" % re.escape(name), text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    nxt = re.search(r"^(def |[A-Za-z_]+ =|# ═)", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def shutil_which_git() -> Optional[str]:
    for cand in (r"E:\git\Git\cmd\git.exe", "git"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=False)
            return cand
        except (OSError, ValueError):
            continue
    return None


# ══════════════════════════════════════════════════════════════ A 基线
def check_baseline() -> None:
    say("[A] 基线：第七批封板状态 + 本批开工点 + 本批文件存在性")
    record("A 基线", "S2 第七批封板记录存在", REFERENCE_DOC.is_file(), str(REFERENCE_DOC))
    record("A 基线", "S2 第八批开工前预检报告存在", START_DOC.is_file(), str(START_DOC))
    for rel in BATCH8_FILES:
        path = BACKEND / rel
        ok = path.is_file() and path.stat().st_size > 200
        record("A 基线", f"本批生产代码 {rel} 存在", ok,
               f"{path.stat().st_size} B" if path.is_file() else "缺失")
        if path.is_file():
            say(f"        sha256[:16]={_sha(path.read_text(encoding='utf-8'))}  {rel}")


# ══════════════════════════════════════════════════════════════ B 范围
def check_scope() -> None:
    say("[B] 范围：接口 34 / 路径 26；A-07 已注册（唯一增量）；上批 33 条全保留")
    sys.path.insert(0, str(BACKEND))
    from app import create_app

    app = create_app("test")
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = {(m, str(r)) for r in rules for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}

    record("B 范围", f"接口总数 = {EXPECTED_ENDPOINTS_COUNT}",
           len(endpoints) == EXPECTED_ENDPOINTS_COUNT, str(len(endpoints)))
    record("B 范围", f"路径总数 = {EXPECTED_PATHS_COUNT}（A-07 复用既有路径）",
           len(paths) == EXPECTED_PATHS_COUNT, str(len(paths)))
    missing = BATCH8_ENDPOINTS - endpoints
    record("B 范围", "A-07（DELETE /users/me）已注册", not missing, repr(sorted(missing)))
    prev_missing = BATCH7_ENDPOINTS - endpoints
    record("B 范围", "S2 第一~七批 33 条接口**全部保留**", not prev_missing,
           repr(sorted(prev_missing)))
    record("B 范围", "接口增量**恰好**为 A-07",
           endpoints - BATCH7_ENDPOINTS == BATCH8_ENDPOINTS,
           repr(sorted((endpoints - BATCH7_ENDPOINTS) - BATCH8_ENDPOINTS)))
    me_rules = [r for r in rules if str(r) == "/api/v1/users/me"]
    me_methods = set()
    for rule in me_rules:
        me_methods |= (rule.methods or set()) - {"HEAD", "OPTIONS"}
    record("B 范围", "/users/me 恰 GET（A-06）+ DELETE（A-07）两个方法",
           me_methods == {"GET", "DELETE"}, repr(sorted(me_methods)))
    record("B 范围", "account 蓝图独立注册且计入蓝图数 10",
           "account" in app.blueprints and len(app.blueprints) == 10,
           repr(sorted(app.blueprints.keys())))
    forbidden = ("/api/v1/reminders", "/api/v1/notifications", "/api/v1/admin",
                 "/api/v1/payments", "/api/v1/membership")
    hits = [(p, f) for p in paths for f in forbidden if p.startswith(f)]
    record("B 范围", "越界模块均未注册", not hits, repr(hits))
    record("B 范围", "/me/data 下仍恰 2 条路径",
           sorted(p for p in paths if p.startswith("/api/v1/me/data")) ==
           ["/api/v1/me/data/clear", "/api/v1/me/data/summary"])


# ══════════════════════════════════════════════════════════════ C 错误码
def check_error_codes() -> None:
    say("[C] 错误码：18 + 7 冻结集合**只增不改**；A-07 0 新增")
    text = _read("app/core/errors.py")
    codes = set(re.findall(r'^\s+([A-Z][A-Z0-9_]+)\s*=\s*"',
                           _class_block(text, "ErrorCode"), re.M))
    field_codes = set(re.findall(r'^\s+([A-Z][A-Z0-9_]+)\s*=\s*"',
                                 _class_block(text, "FieldErrorCode"), re.M))
    record("C 错误码", f"全局错误码恰为冻结 18 个（{len(codes)}）", codes == FROZEN_CODES,
           repr(sorted(codes ^ FROZEN_CODES)))
    record("C 错误码", "字段级码恰为冻结 7 个", field_codes == FROZEN_FIELD_CODES,
           repr(sorted(field_codes ^ FROZEN_FIELD_CODES)))
    svc = _read("app/services/account_service.py")
    used = set(re.findall(r"(?<!Field)ErrorCode\.([A-Z_]+)", svc))
    record("C 错误码", "A-07 仅复用既有全局码（0 新增）",
           used <= {"INVALID_PARAM", "UNAUTHENTICATED", "PASSWORD_INVALID",
                    "VALIDATION_FAILED", "INTERNAL_ERROR"}, repr(sorted(used)))
    f_used = set(re.findall(r"FieldErrorCode\.([A-Z_]+)", svc))
    record("C 错误码", "A-07 仅复用既有字段级码（REQUIRED / INVALID_FORMAT）",
           f_used <= {"REQUIRED", "INVALID_FORMAT"}, repr(sorted(f_used)))
    record("C 错误码", "A-07 密码错误**只**用 PASSWORD_INVALID（无 429 计数/锁定）",
           "ErrorCode.PASSWORD_INVALID" in svc
           and "SESSION_VERIFY_ABORTED" not in svc
           and "ACCOUNT_LOCKED" not in svc
           and "export_pwd_fail_count" not in svc)
    record("C 错误码", "A-07 无「注销专用」新增码",
           "ACCOUNT_CLOSED" not in codes and "ACCOUNT_DELETED" not in codes)


# ══════════════════════════════════════════════════════════ D 封板保护
def check_frozen_files() -> None:
    say("[D] 封板保护：mtime 未越界 + frontend 未改 + git 未提交")
    ref = _mtime(START_DOC) or _mtime(REFERENCE_DOC)
    label = START_DOC.name if _mtime(START_DOC) else REFERENCE_DOC.name
    say(f"        判定边界（本批开工点）：{label}  "
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ref)) if ref else '(缺失)'}")

    protected: List[str] = []
    for root, dirs, files in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", "storage", ".pytest_cache"}]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(root) / name
            rel = "backend/" + path.relative_to(BACKEND).as_posix()
            if not _own(rel):
                protected.append(rel)
    hits = [rel for rel in protected if _mtime(PROJECT / rel) > ref + 1]
    record("D 封板保护", f"backend 受保护 .py 共 {len(protected)} 项，mtime 越界 0",
           not hits, repr(hits[:8]))
    record("D 封板保护", "受保护文件数 > 40（扫描未被绕过）", len(protected) > 40,
           str(len(protected)))

    frontend = []
    froot = PROJECT / "frontend"
    if froot.is_dir():
        for root, dirs, files in os.walk(froot):
            dirs[:] = [d for d in dirs if d not in {"node_modules", "unpackage", ".git"}]
            for name in files:
                frontend.append(Path(root) / name)
    fhits = [p.name for p in frontend if _mtime(p) > ref + 1]
    record("D 封板保护", f"frontend 共 {len(frontend)} 个文件，本批修改 0", not fhits,
           repr(fhits[:8]))

    docs = [p for p in ARTIFACTS.glob("*.md") if p.name not in BATCH8_DOCS]
    dhits = [p.name for p in docs if _mtime(p) > ref + 1]
    record("D 封板保护", f"S0/S1/S2 既有交付物 {len(docs)} 份，改动 0", not dhits,
           repr(dhits[:8]))

    # 历史脚本零改动（batch5/6/7 守卫 + verify）
    hist = [PROJECT / "scripts" / "verify_s2_batch6.py",
            PROJECT / "scripts" / "verify_s2_batch7.py",
            BACKEND / "tests" / "batch5" / "test_batch5_scope_guard.py",
            BACKEND / "tests" / "batch6" / "test_batch6_scope_guard.py",
            BACKEND / "tests" / "batch7" / "test_batch7_scope_guard.py"]
    hhits = [p.name for p in hist if p.is_file() and _mtime(p) > ref + 1]
    record("D 封板保护", f"历史验证脚本 {len(hist)} 份，本批改动 0", not hhits, repr(hhits))

    git = shutil_which_git()
    if git:
        log = subprocess.run([git, "log", "--oneline"], cwd=str(PROJECT),
                             capture_output=True).stdout.decode("utf-8", "replace").strip()
        record("D 封板保护", "git 提交数仍为 1（本批 0 次 add/commit）",
               len([x for x in log.splitlines() if x.strip()]) == 1, log[:120])
    else:
        record("D 封板保护", "git 可用（跳过提交数判定）", False, "未找到 git 可执行文件")


# ══════════════════════════════════════════════════════════════ E 迁移
def check_migration() -> None:
    say("[E] 迁移：唯一 0001_initial_schema，本批 0 新增（无 0002_*）")
    versions = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py")
                      if not p.name.startswith("__"))
    record("E 迁移", "migrations/versions 恰为 0001_initial_schema",
           versions == ["0001_initial_schema.py"], repr(versions))
    record("E 迁移", "**不存在** 0002_*（本批无结构变更）",
           not any(v.startswith("0002") for v in versions))
    migration_text = _read("migrations/versions/0001_initial_schema.py")
    record("E 迁移", "迁移含 8 张业务表的建表语句（A-07 全部为物理删除对象）",
           all(_create_table_block(migration_text, t) for t in FROZEN_TABLES))
    record("E 迁移", "迁移含 user_account / login_failure_state 等账号侧表",
           _create_table_block(migration_text, "user_account") != ""
           and _create_table_block(migration_text, "user_session") != "")


# ══════════════════════════════════════════════════════════════ F 契约
def check_contract() -> None:
    say("[F] 契约：A-07 三重确认 / 8 步删除 / 单事务 / 残留自检 / T4 文件与重试")
    svc = _read("app/services/account_service.py")
    api = _read("app/api/v1/account.py")

    record("F 契约", "确认文字为 A-07 **独立常量**「注销账号」（C1，不复用 D-02）",
           'CONFIRM_TEXT = "注销账号"' in svc
           and '"确认删除"' not in svc
           and "record_service.CONFIRM_TEXT" not in svc)
    record("F 契约", "成功响应 data **恰 1 键** account_closed（C3）",
           'CLOSED_DATA: Dict[str, Any] = {"account_closed": True}' in svc
           and '"soft_warning"' not in svc and '"warnings"' not in svc)
    record("F 契约", "成功文案「账号已注销」（与「退出登录」严格区分）",
           'CLOSED_MESSAGE = "账号已注销"' in svc)
    record("F 契约", "请求参数**不含** acknowledge_irreversible（C2，仅文档声明、代码零键引用）",
           "acknowledge_irreversible" not in api
           and 'get("acknowledge_irreversible")' not in svc
           and '["acknowledge_irreversible"]' not in svc
           and "'acknowledge_irreversible' in payload" not in svc)

    order_block = svc.split("DELETE_ORDER: Tuple[str, ...] = (")[1].split(")")[0]
    order = [s.strip().strip('",') for s in order_block.replace("\n", "").split(",") if s.strip()]
    record("F 契约", "8 步删除顺序**逐字**冻结（账号最后）", tuple(order) == DELETE_ORDER,
           repr(order))
    body = _func_body(svc, "close_account")
    positions = [body.index(f'counts["{name}"]') for name in DELETE_ORDER]
    record("F 契约", "源码 8 次 _purge 次序与冻结顺序一致", positions == sorted(positions))
    record("F 契约", "**不读** deleted_at / 30 天窗口（R-13 核心）",
           not any(k in svc for k in ("SOFT_DELETE_PURGE_DAYS", "purge_days",
                                      ".is_deleted ==", ".is_deleted=",
                                      "HealthRecord.deleted_at", "RecordTag.deleted_at",
                                      "HealthGoal.deleted_at")))
    record("F 契约", "单事务：恰 1 次 commit + 异常 rollback",
           body.count("db.commit()") == 1 and "db.rollback()" in body)
    record("F 契约", "C7 残留自检**先于** commit", body.index("_assert_no_residue(") < body.index("db.commit()"))
    record("F 契约", "残留自检覆盖 8 张表", all(
        t in svc.split("def _residue_criteria")[1].split("def ")[0] for t in DELETE_ORDER))
    record("F 契约", "失败 → 500 INTERNAL_ERROR（整体回滚）",
           "ErrorCode.INTERNAL_ERROR" in body)
    record("F 契约", "T0 密码闸门**先于**任何删除写操作",
           body.index("_verify_login_password(") < body.index('counts["record_tag"]'))
    record("F 契约", "确认文字**先于**密码校验", body.index("_validate_confirm(") < body.index("_verify_login_password("))
    record("F 契约", "export_job **删除前**先取 file_path",
           body.index("job.file_path") < body.index('counts["export_job"]'))
    record("F 契约", "T4 文件删除在 db.commit() **之后**（禁止事务内删文件）",
           body.index("db.commit()") < body.index("_cleanup_export_files("))
    record("F 契约", "文件越界 → 拒绝删除（安全）",
           "导出文件路径越界" in svc and "ValueError" in svc)
    record("F 契约", "login_failure_state **按 username** 删除",
           "LoginFailureState.username == username" in svc)
    record("F 契约", "user_profile **整行删除**（非 D-02 的置空）",
           "_purge(db, UserProfile, UserProfile.user_id == account_id)" in svc
           and "setattr(profile" not in svc and "profile_row" not in svc)

    # C6 重试机制（最小落地）
    record("F 契约", "C6 重试登记落盘（cleanup_retry.jsonl，不入库、不建表）",
           'CLEANUP_RETRY_FILENAME = "cleanup_retry.jsonl"' in svc
           and "__tablename__" not in svc)
    record("F 契约", "C6 重试为**真实可执行**函数（drain_cleanup_retries）",
           "def drain_cleanup_retries(" in svc and "_read_retry_queue" in svc
           and "_write_retry_queue" in svc)
    record("F 契约", "C6 登记内容**只记文件名**（脱敏）",
           'entry = {\n        "file_name": name,' in svc and '"file_path":' not in svc)
    record("F 契约", "删除原语单一入口 _unlink（便于失败注入验证）",
           "def _unlink(path: str) -> None:" in svc and "_unlink(target)" in svc)

    # API 层
    record("F 契约", "A-07 走 require_auth", api.count("@require_auth") == 1,
           str(api.count("@require_auth")))
    record("F 契约", "A-07 使用独立 account 蓝图",
           'bp = Blueprint("account", __name__)' in api)
    record("F 契约", "成功响应走统一 api_response（自动 X-Request-Id）",
           "api_response(" in api and 'code="OK"' in api)
    record("F 契约", "请求体非 JSON 对象 → 400 INVALID_PARAM",
           "ErrorCode.INVALID_PARAM" in api)


# ══════════════════════════════════════════════════════════════ G 安全
def check_security() -> None:
    say("[G] 安全：user_id 只来自 Token / 无范围扩展 / 不误伤他账号 / 日志脱敏")
    svc = _read("app/services/account_service.py")
    api = _read("app/api/v1/account.py")

    record("G 安全", "user_id 只来自 Access Token（current_user_id）",
           "current_user_id()" in api and 'request.args.get("user_id")' not in api
           and 'payload.get("user_id")' not in api)
    client_inputs = ('.get("target_user_id")', '.get("force")', '.get("grace_period")',
                     '.get("defer")', '.get("schedule")', '.get("include_profile_row")',
                     '.get("delete_account")', '.get("include_sessions")',
                     '["target_user_id"]', '["grace_period"]')
    record("G 安全", "**不接受**任何范围扩展参数（入参口径判定）",
           not any(k in svc or k in api for k in client_inputs))
    record("G 安全", "所有删除条件恒带 user_id（账号按 id）",
           svc.count(".user_id == account_id") >= 6 and "UserAccount.id == account_id" in svc)
    record("G 安全", "失败路径不泄漏内部细节（500 走统一处理器）",
           "ErrorCode.INTERNAL_ERROR" in svc and "raise ApiError(ErrorCode.INTERNAL_ERROR)" in svc)
    log_calls = re.findall(r"logger\.(?:info|warning|exception)\(([\s\S]*?)\)\n", svc)
    leak = [c for c in log_calls if "username" in c or "user_id" in c or "file_path" in c]
    record("G 安全", "日志不写 username / user_id / file_path", not leak, repr(leak[:2]))
    record("G 安全", "重试登记不含完整路径 / 用户名（只 basename）",
           "os.path.basename(str(file_name" in svc)
    record("G 安全", "不新增表 / 无迁移写入（无 __tablename__ / create_table）",
           "__tablename__" not in svc and "create_table" not in svc)
    t1 = _read("tests/batch8/test_a07_close_account.py")
    t2 = _read("tests/batch8/test_a07_files_retry.py")
    record("G 安全", "回滚行为化用例存在（任意第 N 步）",
           "test_a07_transaction_rolls_back_on_step_failure" in
           _read("tests/batch8/test_a07_files_retry.py"))
    record("G 安全", "幂等/重复注销用例存在",
           "test_a07_repeat_close_returns_401" in t1)
    record("G 安全", "T4 文件失败仍 200 + 重试登记用例存在",
           "test_a07_file_delete_failure_still_returns_200" in t2
           and "test_a07_file_delete_failure_registers_retry" in t2)
    record("G 安全", "对端账号不受影响用例存在",
           "test_a07_peer_account_untouched" in t1
           and "test_a07_peer_token_cannot_close_others" in t1)


# ══════════════════════════════════════════════════ H 交付物 + 红线
def check_deliverables() -> None:
    say("[H] 交付物 + 医疗红线")
    arts = [
        (SCRIPTS / "verify_s2_batch8.py", 300),
        (SCRIPTS / "s2_batch8_http_smoke.py", 300),
        (SCRIPTS / "s2_batch8_accept.console.txt", 500),
        (SCRIPTS / "s2_batch8_accept.cmd.txt", 100),
        (SCRIPTS / "s2_batch8_accept.sql.txt", 200),
        (SCRIPTS / "b8_cleanup_testdata.py", 300),
        (PROJECT / "S2_第八批_A07_Edge验收脚本.js", 500),
    ]
    for path, min_size in arts:
        ok = path.is_file() and path.stat().st_size > min_size
        record("H 交付物", f"{path.name} 存在且非空", ok,
               f"{path.stat().st_size} B" if path.is_file() else "缺失")

    tests = sorted(p.name for p in (BACKEND / "tests" / "batch8").glob("test_*.py"))
    record("H 交付物", "tests/batch8 用例文件 ≥ 4", len(tests) >= 4, repr(tests))

    edge = PROJECT / "S2_第八批_A07_Edge验收脚本.js"
    if edge.is_file():
        raw = edge.read_bytes()
        text = edge.read_text(encoding="utf-8")
        record("H 交付物", "Edge 脚本反引号 0（交付链路安全）", raw.count(0x60) == 0,
               f"backtick={raw.count(0x60)}")
        record("H 交付物", "Edge 脚本静态断言点 ≥ 60",
               text.count("ok(") + text.count("okEq(") >= 60,
               str(text.count("ok(") + text.count("okEq(")))

    for rel in BATCH8_FILES:
        text = _read(rel)
        hits = [(n, line.strip()[:100]) for n, line in enumerate(text.splitlines(), 1)
                if not _is_exempt(line) for term in BANNED_TERMS if term in line]
        record("H 交付物", f"红线扫描 {rel} 无医学内容", not hits, repr(hits[:4]))


# ══════════════════════════════════════════════════════════════ F-DB
def check_db() -> None:
    say("[F-DB] 只读连库：结构指纹 + 测试残留卫生 + EXPORT_DIR 卫生")
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    from app.core.config import load_config

    # ★ 本机事实：``.env.test`` 的 DB 凭据为占位值，且 ``_load_env_files()`` 用
    #   ``override=False``；本脚本 [B] 段已 ``create_app("test")`` ⇒ 必须先以
    #   ``override=True`` 重载 ``.env.development``（仅进程内存 env）才能连库。
    load_dotenv(BACKEND / ".env.development", override=True)
    engine = create_engine(load_config("development")["SQLALCHEMY_DATABASE_URI"])
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).all()]
        record("F-DB", f"表数量 = {EXPECTED_TABLE_COUNT}（8 业务 + 迁移表）",
               len(tables) == EXPECTED_TABLE_COUNT, repr(sorted(tables)))

        idx = conn.execute(text(
            "SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND index_name <> 'PRIMARY'"
        )).scalar()
        record("F-DB", "非主键索引数 = 17（DISTINCT 口径）", int(idx) == 17, str(idx))

        fk = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = DATABASE() AND constraint_type = 'FOREIGN KEY'"
        )).scalar()
        record("F-DB", "外键数 = 0（A-07 完整性由服务层自检承担）", int(fk) == 0, str(fk))

        version = conn.execute(text(f"SELECT version_num FROM {MIGRATION_TABLE}")).scalar()
        record("F-DB", "alembic_version = 0001_initial_schema",
               str(version) == "0001_initial_schema", str(version))

        for table in ("user_account", "user_profile", "user_session",
                      "login_failure_state", "export_job"):
            cols = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = DATABASE() AND table_name = '{table}'"
            )).all()}
            record("F-DB", f"{table} 无软删列（A-07 物理删除对象）",
                   "is_deleted" not in cols)
        goal_cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'health_goal'"
        )).all()}
        record("F-DB", "health_goal 含 deleted_marker（A-07 一并物理删除）",
               "deleted_marker" in goal_cols)
        record("F-DB", "health_record / record_tag 含软删列（A-07 需含软删行）",
               all("is_deleted" in {r[0] for r in conn.execute(text(
                   "SELECT column_name FROM information_schema.columns "
                   f"WHERE table_schema = DATABASE() AND table_name = '{t}'"
               )).all()} for t in ("health_record", "record_tag")))

        counts = {t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
                  for t in FROZEN_TABLES}
        say(f"        各表行数：{counts}")
        say(f"        合计：{sum(counts.values())}")
        leftover = conn.execute(text(
            "SELECT COUNT(*) FROM user_account WHERE username LIKE 'tst%'"
        )).scalar()
        record("F-DB", "无 tst 测试账号残留", int(leftover or 0) == 0, str(leftover))
        active = int(conn.execute(text(
            "SELECT COUNT(*) FROM export_job e LEFT JOIN user_account a ON a.id = e.user_id "
            "WHERE a.username LIKE 'tst%'"
        )).scalar() or 0)
        record("F-DB", "无 tst 测试账号遗留导出任务", active == 0, str(active))

    export_dir = BACKEND / "storage" / "exports"
    files = sorted(p.name for p in export_dir.glob("*")) if export_dir.is_dir() else []
    say(f"        storage/exports 文件数：{len(files)}  {files[:5]}")
    record("F-DB", "storage/exports 为 0 文件", not files, repr(files[:6]))


# ══════════════════════════════════════════════════════════════ main
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="store_true", help="追加只读连库核验")
    args = parser.parse_args()

    say("=" * 72)
    say("S2 第八批 A-07（注销账号）—— 本批核验（A~H）")
    say("=" * 72)
    check_baseline()
    check_scope()
    check_error_codes()
    check_frozen_files()
    check_migration()
    check_contract()
    check_security()
    check_deliverables()
    if args.db:
        check_db()

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    say("=" * 72)
    say(f"合计：{passed}/{total} PASS，{total - passed} FAIL")
    by_section = {}
    for item in results:
        key = item["section"]
        by_section.setdefault(key, [0, 0])
        by_section[key][1] += 1
        by_section[key][0] += 1 if item["ok"] else 0
    say("分段：" + " | ".join(f"{k} {v[0]}/{v[1]}" for k, v in by_section.items()))
    if total - passed:
        say("失败项：")
        for item in results:
            if not item["ok"]:
                say(f"  - [{item['section']}] {item['name']}  {item['detail']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
