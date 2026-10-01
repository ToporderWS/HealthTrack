# -*- coding: utf-8 -*-
"""S2 第七批 D-01～D-02（数据总览 / 清空全部数据）—— 本批**唯一**回归判定脚本（A~H 八段）。

用法：
- ``python scripts/verify_s2_batch7.py``          只读静态核验（默认）
- ``python scripts/verify_s2_batch7.py --db``     追加**只读**连库核验（F-DB 段）

约定：
- **只读**：不写库、不改文件、不执行 DDL；
- 输出可落盘复用（``> .workbuddy/_b7verify.txt``），**不使用**任何管道；
- 判定口径与 S2 第一~六批一致（``record(section, name, ok, detail)``）；
- 历史批次（batch5 / batch6）守卫脚本把它们**当时**的接口集合硬编码，本批新增
  ``D-01`` / ``D-02`` 后必然 FAIL —— 属**历史时点判据**，处置 = **零改动 + 显式豁免**；
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

#: 基线参照点：S2 第六批封板记录（batch7 之前最后一枚"时点印章"）
REFERENCE_DOC = ARTIFACTS / "S2-第六批-验收通过与封板记录.md"

#: **本批开工点**：Step 0 只读预检报告（batch7 第一件产物）。
#: ``[D]`` 段的"既有交付物是否被改动"必须以**本批开工点**为界 —— 用上一批封板记录作界，
#: 会把它之后本批新增的报告误判为"既有交付物被改动"（假 FAIL）。
START_DOC = ARTIFACTS / "S2-第七批-D01至D02-开工前只读预检报告.md"

#: 本批新增 / 修改的生产代码（相对 backend/）
BATCH7_FILES = (
    "app/__init__.py",
    "app/services/data_service.py",
    "app/api/v1/data.py",
)

#: 本批新增的交付物（不属于"受保护文件"）
BATCH7_OWN = {
    "backend/tests/batch7",
    "backend/app/__init__.py",
    "backend/app/services/data_service.py",
    "backend/app/api/v1/data.py",
    "scripts/verify_s2_batch7.py",
    "scripts/s2_batch7_http_smoke.py",
    "scripts/s2_batch7_accept.console.txt",
    "scripts/s2_batch7_accept.cmd.txt",
    "scripts/s2_batch7_accept.sql.txt",
    "S2_第七批_D01-D02_Edge验收脚本.js",
}

#: 本批新建的文档（不参与"已封板成果未改动"判定）
BATCH7_DOCS = {
    "S2-第七批-D01至D02-开工前只读预检报告.md",
    "S2-第七批-D01至D02-Step1实现报告.md",
    "S2-第七批-D01至D02-验收通过与封板记录.md",
}

#: 8 张业务表 + 迁移表
FROZEN_TABLES = ["user_account", "user_profile", "health_record", "record_tag",
                 "health_goal", "user_session", "login_failure_state", "export_job"]
MIGRATION_TABLE = "alembic_version"
EXPECTED_TABLE_COUNT = 9

#: 冻结错误码（18 个）
FROZEN_CODES = {
    "INVALID_PARAM", "UNAUTHENTICATED", "CREDENTIALS_INVALID", "TOKEN_REUSED",
    "RESOURCE_NOT_FOUND", "USERNAME_TAKEN", "GOAL_TYPE_EXISTS", "EXPORT_IN_PROGRESS",
    "IDEMPOTENCY_CONFLICT", "COUNT_MISMATCH", "EXPORT_EXPIRED", "VALIDATION_FAILED",
    "PASSWORD_INVALID", "ACCOUNT_LOCKED", "SESSION_VERIFY_ABORTED", "SOFT_WARNING",
    "INTERNAL_ERROR", "SERVICE_UNAVAILABLE",
}
FROZEN_FIELD_CODES = {"REQUIRED", "INVALID_TYPE", "INVALID_FORMAT", "WEAK_PASSWORD",
                      "MISMATCH", "SAME_AS_OLD", "NOT_ACCEPTED"}

#: 本批新增（2 条接口 / 2 条唯一路径）
BATCH7_ENDPOINTS = {
    ("GET", "/api/v1/me/data/summary"),
    ("POST", "/api/v1/me/data/clear"),
}
EXPECTED_ENDPOINTS_COUNT = 33
EXPECTED_PATHS_COUNT = 26

#: S2 第六批封板时的 31 条接口（本批必须全部保留）
BATCH6_ENDPOINTS = {
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
}

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
    return any(rel_posix == o or rel_posix.startswith(o + "/") for o in BATCH7_OWN)


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in EXEMPT_MARKERS)


def _class_block(text: str, name: str) -> str:
    """提取**顶层类** ``name`` 的完整类体（到下一个顶层 ``class`` 或文末为止）。"""
    match = re.search(r"^class %s\b[\s\S]*?(?=^class |\Z)" % re.escape(name), text, re.M)
    return match.group(0) if match else ""


def _create_table_block(text: str, table: str) -> str:
    """按**括号配平**切出 ``op.create_table("<table>", ...)`` 的实参原文。"""
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
    say("[A] 基线：第六批封板状态 + 本批文件存在性")
    record("A 基线", "S2 第六批封板记录存在", REFERENCE_DOC.is_file(), str(REFERENCE_DOC))
    record("A 基线", "S2 第六批 Step1 实现报告存在",
           (ARTIFACTS / "S2-第六批-E01至E04-Step1实现报告.md").is_file())
    record("A 基线", "S2 第七批开工前预检报告存在", START_DOC.is_file())
    for rel in BATCH7_FILES:
        path = BACKEND / rel
        ok = path.is_file() and path.stat().st_size > 200
        record("A 基线", f"本批生产代码 {rel} 存在", ok,
               f"{path.stat().st_size} B" if path.is_file() else "缺失")
        if path.is_file():
            say(f"        sha256[:16]={_sha(path.read_text(encoding='utf-8'))}  {rel}")


# ══════════════════════════════════════════════════════════════ B 范围
def check_scope() -> None:
    say("[B] 范围：接口 33 / 路径 26；A-07 与第八批模块未注册")
    sys.path.insert(0, str(BACKEND))
    from app import create_app

    app = create_app("test")
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = {(m, str(r)) for r in rules for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}

    record("B 范围", f"接口总数 = {EXPECTED_ENDPOINTS_COUNT}",
           len(endpoints) == EXPECTED_ENDPOINTS_COUNT, str(len(endpoints)))
    record("B 范围", f"路径总数 = {EXPECTED_PATHS_COUNT}",
           len(paths) == EXPECTED_PATHS_COUNT, str(len(paths)))
    missing = BATCH7_ENDPOINTS - endpoints
    record("B 范围", "D-01 / D-02 全部注册", not missing, repr(sorted(missing)))
    record("B 范围", "D-01 / D-02 覆盖 2 条接口 / 2 条唯一路径",
           len(BATCH7_ENDPOINTS) == 2 and len({p for _m, p in BATCH7_ENDPOINTS}) == 2)
    prev_missing = BATCH6_ENDPOINTS - endpoints
    record("B 范围", "S2 第二~六批 31 条接口**全部保留**", not prev_missing,
           repr(sorted(prev_missing)))
    record("B 范围", "界面增量**恰好**为 D-01 / D-02",
           endpoints - BATCH6_ENDPOINTS == BATCH7_ENDPOINTS,
           repr(sorted((endpoints - BATCH6_ENDPOINTS) - BATCH7_ENDPOINTS)))
    record("B 范围", "A-07（DELETE /users/me）**未**注册",
           ("DELETE", "/api/v1/users/me") not in endpoints)
    forbidden = ("/api/v1/reminders", "/api/v1/notifications", "/api/v1/admin",
                 "/api/v1/payments", "/api/v1/membership")
    hits = [(p, f) for p in paths for f in forbidden if p.startswith(f)]
    record("B 范围", "第八批 / 越界模块均未注册", not hits, repr(hits))
    mine = sorted(p for p in paths if p.startswith("/api/v1/me/data"))
    record("B 范围", "/me/data 下恰 2 条路径",
           mine == ["/api/v1/me/data/clear", "/api/v1/me/data/summary"], repr(mine))


# ══════════════════════════════════════════════════════════════ C 错误码
def check_error_codes() -> None:
    say("[C] 错误码：18 + 7 冻结集合**只增不改**")
    text = _read("app/core/errors.py")
    codes = set(re.findall(r'^\s+([A-Z][A-Z0-9_]+)\s*=\s*"',
                           _class_block(text, "ErrorCode"), re.M))
    field_codes = set(re.findall(r'^\s+([A-Z][A-Z0-9_]+)\s*=\s*"',
                                 _class_block(text, "FieldErrorCode"), re.M))
    record("C 错误码", f"全局错误码恰为冻结 18 个（{len(codes)}）", codes == FROZEN_CODES,
           repr(sorted(codes ^ FROZEN_CODES)))
    record("C 错误码", "字段级码恰为冻结 7 个", field_codes == FROZEN_FIELD_CODES,
           repr(sorted(field_codes ^ FROZEN_FIELD_CODES)))
    # D-01 / D-02 只用既有码（本批 0 新增）
    svc = _read("app/services/data_service.py")
    for code in ("PASSWORD_INVALID", "VALIDATION_FAILED", "INTERNAL_ERROR",
                 "INVALID_PARAM", "UNAUTHENTICATED"):
        record("C 错误码", f"复用既有码 {code}（未新增）", code in codes)
    record("C 错误码", "D-02 密码错误**只**用 PASSWORD_INVALID（无 429 计数逻辑）",
           "ErrorCode.PASSWORD_INVALID" in svc
           and "SESSION_VERIFY_ABORTED" not in svc
           and "export_pwd_fail_count" not in svc
           and "ACCOUNT_LOCKED" not in svc
           and "LoginFailureState" not in svc)


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

    docs = [p for p in ARTIFACTS.glob("*.md") if p.name not in BATCH7_DOCS]
    dhits = [p.name for p in docs if _mtime(p) > ref + 1]
    record("D 封板保护", f"S0/S1/S2 既有交付物 {len(docs)} 份，改动 0", not dhits,
           repr(dhits[:8]))

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
    record("E 迁移", "迁移内含 health_goal.deleted_marker（D-02 释放唯一约束所依赖）",
           "deleted_marker" in _create_table_block(migration_text, "health_goal"))
    record("E 迁移", "迁移内含 user_profile 6 个健康字段（D-02 置空对象）",
           all(f in _create_table_block(migration_text, "user_profile") for f in
               ("height_cm", "initial_weight_kg", "blood_type",
                "medical_history", "allergy_history", "medication_notes")))


# ══════════════════════════════════════════════════════════════ F 契约
def check_contract() -> None:
    say("[F] 契约：D-01 结构 / D-02 范围与文案 / 单事务 / 保留清单")
    svc = _read("app/services/data_service.py")
    api = _read("app/api/v1/data.py")

    # ── D-01 ──
    summary_body = svc.split("def summary")[1].split("def clear_message")[0]
    # 顶层键：只取 `summary` 的 `return { ... }` 块（不得把 by_metric.append 的内层键算进来）
    top_block = summary_body.split("return {")[-1]
    keys = set(re.findall(r'"([a-z_]+)":', top_block))
    expected = {"total_records", "by_metric", "goals", "profile"}
    record("F 契约", "D-01 顶层恰 4 键（total_records / by_metric / goals / profile）",
           keys == expected, repr(sorted(keys ^ expected)))
    # 每项键：只取 `by_metric.append({ ... })` 块
    item_block = summary_body.split("by_metric.append({")[1].split("})")[0]
    item_keys = set(re.findall(r'"([a-z_]+)":', item_block))
    expected_item = {"metric_type", "count", "first_recorded_at", "last_recorded_at"}
    record("F 契约", "D-01 by_metric 每项恰 4 键", item_keys == expected_item,
           repr(sorted(item_keys ^ expected_item)))
    record("F 契约", "D-01 按 METRIC_TYPES **固定顺序**输出（C3）",
           "for metric_type in metric_rules.METRIC_TYPES:" in summary_body)
    record("F 契约", "D-01 **只**返回有数据的指标（无数据不返回 0 行）",
           "if item is None:" in summary_body and "continue" in summary_body)
    record("F 契约", "D-01 goals 键 = active_count / paused_count",
           '{"active_count": active, "paused_count": paused}' in svc)
    record("F 契约", "D-01 profile 6 字段 filled / total（C4）",
           '"health_fields_filled": filled, "health_fields_total": HEALTH_FIELDS_TOTAL' in svc)
    record("F 契约", "D-01 不含任何数值统计字段",
           not ({"avg", "min", "max", "sum", "chart", "points", "trend"} & keys))

    # ── D-02 ──
    record("F 契约", "D-02 复用 R-06 冻结确认文字常量（单一数据源）",
           "CONFIRM_TEXT = record_service.CONFIRM_TEXT" in svc
           and '"确认删除"' not in svc)
    record("F 契约", "D-02 scope **逐字逐序**冻结（C5）",
           'CLEAR_SCOPE: Tuple[str, ...] = (\n    "health_records",\n    "record_tags",\n'
           '    "goals",\n    "profile_health_fields",\n)' in svc)
    record("F 契约", "D-02 成功响应恰 6 键（无 soft_warning / warnings，C6）",
           all(k in svc for k in ('"deleted_records"', '"deleted_tags"', '"deleted_goals"',
                                  '"profile_health_fields_cleared"', '"account_kept"',
                                  '"scope"'))
           and "soft_warning" not in svc and "warnings" not in svc)
    record("F 契约", "D-02 成功文案模板（含清除条数 + 账号保留）",
           'CLEAR_MESSAGE = "已清除 {count} 条记录。账号保留，数据已按规则清除"' in svc)
    record("F 契约", "D-02 三重确认：确认文字 + 密码 + 不可恢复声明",
           "confirm_text" in svc and "acknowledge_irreversible" in svc
           and "_verify_login_password" in svc)
    record("F 契约", "D-02 不可恢复声明必须是布尔 true",
           'payload.get("acknowledge_irreversible") is not True' in svc)
    clear_body = svc.split("def clear_all_data")[1]
    record("F 契约", "D-02 **单事务**（恰 1 次 commit）+ 异常 rollback",
           clear_body.count("db.commit()") == 1 and "db.rollback()" in clear_body)
    record("F 契约", "D-02 失败 → 500 INTERNAL_ERROR（整体回滚，不得清一半）",
           "ErrorCode.INTERNAL_ERROR" in clear_body)
    record("F 契约", "D-02 health_goal **deleted_marker = id**（释放唯一约束）",
           "row.deleted_marker = int(row.id)" in svc)
    record("F 契约", "D-02 record_tag **随主记录同步软删**",
           "row.is_deleted = 1" in svc.split("def _soft_delete_tags")[1].split("def ")[0])
    record("F 契约", "D-02 档案**仅置空 6 个健康字段**（保留档案行）",
           "setattr(profile, field, None)" in svc
           and '"nickname"' not in svc and '"gender"' not in svc)
    retention_ok = (
        "保留账号" in svc
        and "不删除" in svc
        and all(t in svc for t in ("user_account", "user_profile", "user_session",
                                   "login_failure_state", "export_job"))
    )
    record("F 契约", "D-02 明确**保留**清单已在文档中列明", retention_ok)
    record("F 契约", "D-02 请求体非 dict → 400 INVALID_PARAM",
           "ErrorCode.INVALID_PARAM" in api)

    # ── API 层 ──
    record("F 契约", "D-01 / D-02 均走 require_auth",
           api.count("@require_auth") == 2, str(api.count("@require_auth")))
    record("F 契约", "成功响应走统一 api_response（自动 X-Request-Id）",
           "api_response(" in api and "code=\"OK\"" in api)


# ══════════════════════════════════════════════════════════════ G 安全
def check_security() -> None:
    say("[G] 安全：身份隔离 / 软删过滤 / 越权 / 无范围扩展")
    svc = _read("app/services/data_service.py")
    api = _read("app/api/v1/data.py")

    record("G 安全", "D-01 取数恒带 user_id 条件", "HealthRecord.user_id == user_id" in svc)
    record("G 安全", "D-01 恒带 is_deleted == 0（软删不计入）",
           "HealthRecord.is_deleted == 0" in svc and "HealthGoal.is_deleted == 0" in svc)
    record("G 安全", "D-02 目标/记录/标签 取数恒带 user_id",
           svc.count("user_id == user_id") >= 4, str(svc.count("user_id == user_id")))
    record("G 安全", "user_id 只来自 Access Token（current_user_id）",
           "current_user_id()" in api and 'request.args.get("user_id")' not in api
           and 'payload.get("user_id")' not in api)
    client_inputs = ('.get("include_profile_row")', '.get("delete_account")',
                     '.get("include_sessions")', '.get("purge_all")',
                     '["include_profile_row"]', '["delete_account"]')
    record("G 安全", "**不接受**任何范围扩展参数（入参口径判定）",
           not any(k in svc or k in api for k in client_inputs))
    record("G 安全", "D-02 **不触碰**账号 / 会话 / 导出任务 / 登录失败状态",
           not any(k in svc for k in ("delete(UserAccount", "delete(UserSession",
                                      "delete(ExportJob", "delete(LoginFailureState)")))
    record("G 安全", "D-02 密码校验**先于**任何写操作（无豁免、无部分执行）",
           clear_body_order(svc))
    record("G 安全", "D-02 不写任何密码 / Token 到日志",
           "password" not in svc.split("logger.info")[1].split(")")[0]
           and "token" not in svc.split("logger.info")[1].split(")")[0])
    record("G 安全", "D-02 不清空时也不误删（返回计数与 DB 变化量一致，由用例背书）",
           "test_d02_records_soft_deleted_physical_rows_kept" in
           (BACKEND / "tests" / "batch7" / "test_d02_clear.py").read_text(encoding="utf-8"))
    record("G 安全", "事务失败整体回滚有行为化用例背书",
           "test_d02_transaction_rolls_back_on_failure" in
           (BACKEND / "tests" / "batch7" / "test_d02_clear.py").read_text(encoding="utf-8"))


def clear_body_order(svc: str) -> bool:
    body = svc.split("def clear_all_data")[1]
    gate = body.find("_verify_login_password(")
    write = body.find("_soft_delete_records(")
    return gate != -1 and write != -1 and gate < write


# ══════════════════════════════════════════════════ H 交付物 + 红线
def check_deliverables() -> None:
    say("[H] 交付物 + 医疗红线")
    arts = [
        (SCRIPTS / "verify_s2_batch7.py", 300),
        (SCRIPTS / "s2_batch7_http_smoke.py", 300),
        (SCRIPTS / "s2_batch7_accept.console.txt", 500),
        (SCRIPTS / "s2_batch7_accept.cmd.txt", 100),
        (SCRIPTS / "s2_batch7_accept.sql.txt", 200),
        (PROJECT / "S2_第七批_D01-D02_Edge验收脚本.js", 500),
    ]
    for path, min_size in arts:
        ok = path.is_file() and path.stat().st_size > min_size
        record("H 交付物", f"{path.name} 存在且非空", ok,
               f"{path.stat().st_size} B" if path.is_file() else "缺失")

    tests = sorted(p.name for p in (BACKEND / "tests" / "batch7").glob("test_*.py"))
    record("H 交付物", "tests/batch7 用例文件 ≥ 4", len(tests) >= 4, repr(tests))

    edge = PROJECT / "S2_第七批_D01-D02_Edge验收脚本.js"
    if edge.is_file():
        raw = edge.read_bytes()
        text = edge.read_text(encoding="utf-8")
        record("H 交付物", "Edge 脚本反引号 0（交付链路安全）", raw.count(0x60) == 0,
               f"backtick={raw.count(0x60)}")
        record("H 交付物", "Edge 脚本静态断言点 ≥ 60",
               text.count("ok(") + text.count("okEq(") >= 60,
               str(text.count("ok(") + text.count("okEq(")))

    for rel in BATCH7_FILES:
        text = _read(rel)
        hits = [(n, line.strip()[:100]) for n, line in enumerate(text.splitlines(), 1)
                if not _is_exempt(line) for term in BANNED_TERMS if term in line]
        record("H 交付物", f"红线扫描 {rel} 无医学内容", not hits, repr(hits[:4]))


# ══════════════════════════════════════════════════════════════ F-DB
def _connect(cfg):
    from sqlalchemy import create_engine

    return create_engine(cfg["SQLALCHEMY_DATABASE_URI"])


def check_db() -> None:
    say("[F-DB] 只读连库：结构指纹 + 测试残留卫生")
    from dotenv import load_dotenv
    from sqlalchemy import text

    from app.core.config import load_config

    # ★ 本机事实：``.env.test`` 的 DB 凭据是占位值（MYSQL_USER=CHANGE_ME），而
    #   ``config._load_env_files()`` 对 ``.env.<env>`` 用 ``override=False``；
    #   本脚本在 [B] 段先执行过 ``create_app("test")`` ⇒ 占位值占据 ``os.environ``，
    #   之后 ``load_config("development")`` 无法覆盖 → 连库必然 1045。
    #   故显式以 ``override=True`` 重载 ``.env.development``（**仅进程内存 env**）。
    load_dotenv(BACKEND / ".env.development", override=True)
    engine = _connect(load_config("development"))
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).all()]
        record("F-DB", f"表数量 = {EXPECTED_TABLE_COUNT}（8 业务 + 迁移表）",
               len(tables) == EXPECTED_TABLE_COUNT, repr(sorted(tables)))

        # 注意：``information_schema.statistics`` 每索引每列一行 ⇒ 索引**个数**须 DISTINCT
        idx = conn.execute(text(
            "SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND index_name <> 'PRIMARY'"
        )).scalar()
        record("F-DB", "非主键索引数 = 17（DISTINCT 口径）", int(idx) == 17, str(idx))

        fk = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints "
            "WHERE table_schema = DATABASE() AND constraint_type = 'FOREIGN KEY'"
        )).scalar()
        record("F-DB", "外键数 = 0", int(fk) == 0, str(fk))

        version = conn.execute(text(f"SELECT version_num FROM {MIGRATION_TABLE}")).scalar()
        record("F-DB", "alembic_version = 0001_initial_schema",
               str(version) == "0001_initial_schema", str(version))

        profile_cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'user_profile'"
        )).all()}
        record("F-DB", "user_profile 含 6 个健康字段（D-02 置空对象）",
               {"height_cm", "initial_weight_kg", "blood_type", "medical_history",
                "allergy_history", "medication_notes"} <= profile_cols)
        record("F-DB", "user_profile 无软删列（冻结：档案行不软删）",
               "is_deleted" not in profile_cols)

        goal_cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'health_goal'"
        )).all()}
        record("F-DB", "health_goal 含 deleted_marker（D-02 释放唯一约束）",
               "deleted_marker" in goal_cols)

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


# ══════════════════════════════════════════════════════════════ main
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="store_true", help="追加只读连库核验")
    args = parser.parse_args()

    say("=" * 72)
    say("S2 第七批 D-01~D-02（数据总览 / 清空全部数据）—— 本批核验（A~H）")
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
