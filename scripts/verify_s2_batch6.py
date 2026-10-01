# -*- coding: utf-8 -*-
"""S2 第六批 E-01～E-04（数据导出）—— 本批**唯一**回归判定脚本（A~H 八段）。

用法：
- ``python scripts/verify_s2_batch6.py``          只读静态核验（默认）
- ``python scripts/verify_s2_batch6.py --db``     追加**只读**连库核验（F-DB 段）

约定：
- **只读**：不写库、不改文件、不执行 DDL；
- 输出可落盘复用（``> .workbuddy/_b6verify.txt``），**不使用**任何管道；
- 判定口径与 S2 第一~五批一致（``record(section, name, ok, detail)``）。
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

#: 基线参照点：第五批封板记录（batch6 之前最后一枚"时点印章"）
REFERENCE_DOC = ARTIFACTS / "S2-第五批-验收通过与封板记录.md"

#: **本批开工点**：Step 0 只读预检报告（batch6 第一件产物）。
#: ``[D]`` 段的"既有交付物是否被改动"必须以**本批开工点**为界，而不是以封板记录为界 ——
#: 第五批自身"先写封板记录、后写开发完成报告"会留下数秒的合法时差（实测 16:47:43 → 16:47:46），
#: 若以封板记录为界会把该文件误判为本批改动（假 FAIL）。
START_DOC = ARTIFACTS / "S2-第六批-E01至E04-开工前只读预检报告.md"

#: 本批新增 / 修改的生产代码（相对 backend/）
BATCH6_FILES = (
    "app/__init__.py",
    "app/services/export_service.py",
    "app/api/v1/exports.py",
)

#: 本批新增的交付物（不属于"受保护文件"）
BATCH6_OWN = {
    "backend/tests/batch6",
    "backend/app/__init__.py",
    "backend/app/services/export_service.py",
    "backend/app/api/v1/exports.py",
    "scripts/verify_s2_batch6.py",
    "scripts/s2_batch6_http_smoke.py",
    "scripts/b6_cleanup_exports.py",
    "scripts/s2_batch6_accept.console.txt",
    "scripts/s2_batch6_accept.cmd.txt",
    "scripts/s2_batch6_accept.sql.txt",
    "S2_第六批_E01-E04_Edge验收脚本.js",
}

#: 本批新建的文档（不参与"已封板成果未改动"判定）
BATCH6_DOCS = {
    "S2-第六批-E01至E04-开工前只读预检报告.md",
    "S2-第六批-E01至E04-Step1实现报告.md",
    #: 2026-09-14 追加（第 3 份本批文档产物）：E-03 唯一 FAIL 专项诊断报告。
    #: 该 FAIL 经字节级取证确认属**验收脚本**对 CRLF 的误判（生产代码 0 改动）；
    #: 文件为本批新增产物，必须登记白名单，否则会被 [D] 段误判为
    #: "既有交付物被改动"（假 FAIL）。仅登记，不改任何判定逻辑。
    "S2-第六批-E03空数据下载FAIL专项诊断报告.md",
    #: 2026-09-14 追加（第 4 份本批文档产物）：最终验收前置复核报告
    #: （B4 清理后端到端复核的最终版）。同上：仅登记，不改判定逻辑。
    "S2-第六批-最终验收前置复核报告.md",
    #: 2026-09-14 追加（第 5 份本批文档产物）：封板记录（SEALED 记录）。
    #: 同上：仅登记，不改任何判定逻辑、不降强度。
    "S2-第六批-验收通过与封板记录.md",
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

#: 本批新增（4 条接口 / 3 条路径）
BATCH6_ENDPOINTS = {
    ("POST", "/api/v1/exports"),
    ("GET", "/api/v1/exports"),
    ("GET", "/api/v1/exports/<int:export_id>"),
    ("GET", "/api/v1/exports/<int:export_id>/download"),
}
EXPECTED_ENDPOINTS_COUNT = 31
EXPECTED_PATHS_COUNT = 24

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
    return any(rel_posix == o or rel_posix.startswith(o + "/") for o in BATCH6_OWN)


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in EXEMPT_MARKERS)


# ══════════════════════════════════════════════════════════════ A 基线
def check_baseline() -> None:
    say("[A] 基线：第五批封板状态 + 本批文件存在性")
    record("A 基线", "S2 第五批封板记录存在", REFERENCE_DOC.is_file(),
           str(REFERENCE_DOC))
    record("A 基线", "S2 第五批开发完成报告存在",
           (ARTIFACTS / "S2-第五批开发完成报告.md").is_file())
    for rel in BATCH6_FILES:
        path = BACKEND / rel
        ok = path.is_file() and path.stat().st_size > 200
        record("A 基线", f"本批生产代码 {rel} 存在", ok,
               f"{path.stat().st_size} B" if path.is_file() else "缺失")
        if path.is_file():
            say(f"        sha256[:16]={_sha(path.read_text(encoding='utf-8'))}  {rel}")


# ══════════════════════════════════════════════════════════════ B 范围
def check_scope() -> None:
    say("[B] 范围：接口 31 / 路径 24；无越界模块")
    sys.path.insert(0, str(BACKEND))
    from app import create_app

    app = create_app("test")
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = {(m, str(r)) for r in rules for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}

    record("B 范围", f"接口总数 = {EXPECTED_ENDPOINTS_COUNT}", len(endpoints) == EXPECTED_ENDPOINTS_COUNT,
           str(len(endpoints)))
    record("B 范围", f"路径总数 = {EXPECTED_PATHS_COUNT}", len(paths) == EXPECTED_PATHS_COUNT,
           str(len(paths)))
    missing = BATCH6_ENDPOINTS - endpoints
    record("B 范围", "E-01~E-04 全部注册", not missing, repr(sorted(missing)))
    a07 = [r for r in rules if str(r) == "/api/v1/users/me" and "DELETE" in (r.methods or set())]
    record("B 范围", "A-07 注销接口**未**注册（不越界）", not a07)
    forbidden = ("/api/v1/data", "/api/v1/me/data", "/api/v1/reminders",
                 "/api/v1/admin", "/api/v1/payments")
    hits = [(p, f) for p in paths for f in forbidden if p.startswith(f)]
    record("B 范围", "D-01/D-02、提醒/管理/支付 均未注册", not hits, repr(hits))
    record("B 范围", "E-01~E-04 覆盖 4 条接口 / 3 条唯一路径",
           len(BATCH6_ENDPOINTS) == 4 and len({p for _m, p in BATCH6_ENDPOINTS}) == 3)


# ══════════════════════════════════════════════════════════════ C 错误码
def _class_block(text: str, name: str) -> str:
    """提取**顶层类** ``name`` 的完整类体（到下一个顶层 ``class`` 或文末为止）。

    必须按类切块：``app/core/errors.py`` 中 ``ErrorCode``（18 个）与 ``FieldErrorCode``（7 个）
    缩进完全一致，用「全文 scan ``^\\s{4}NAME = "``」会把两者混为一集合（25 ≠ 18）而误判。
    """
    match = re.search(r"^class %s\b[\s\S]*?(?=^class |\Z)" % re.escape(name), text, re.M)
    return match.group(0) if match else ""


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
    for code in ("EXPORT_IN_PROGRESS", "EXPORT_EXPIRED", "RESOURCE_NOT_FOUND",
                 "PASSWORD_INVALID", "SESSION_VERIFY_ABORTED"):
        record("C 错误码", f"复用既有码 {code}（未新增）", code in codes)


# ══════════════════════════════════════════════════════════════ D 封板保护
def check_frozen_files() -> None:
    say("[D] 封板保护：mtime 未越界 + frontend 未改 + git 未提交")
    # 边界 = **本批开工点**（Step 0 预检报告）；缺失时回退到第五批封板记录。
    # 若用封板记录作边界，会把第五批自身「封板记录 → 开发完成报告」的合法数秒时差误判为
    # 本批改动（实测 16:47:43 vs 16:47:46）。
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

    docs = [p for p in ARTIFACTS.glob("*.md") if p.name not in BATCH6_DOCS]
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


def shutil_which_git() -> Optional[str]:
    for cand in (r"E:\git\Git\cmd\git.exe", "git"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=False)
            return cand
        except (OSError, ValueError):
            continue
    return None


# ══════════════════════════════════════════════════════════════ E 迁移
def _create_table_block(text: str, table: str) -> str:
    """提取 ``op.create_table("<table>", ...)`` 的**括号内**原文。

    必须精确切块：``is_deleted`` 在多张表里重复出现，而 ``export_job`` 又出现在迁移文件
    **开头的文档字符串**里；用固定字符窗口（``export_job[\\s\\S]{0,1200}?is_deleted``）会跨表
    误命中（实测假 FAIL）。此处按括号配平切出该表的建表实参。
    """
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


def check_migration() -> None:
    say("[E] 迁移：唯一 0001_initial_schema，本批 0 新增")
    versions = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py")
                      if not p.name.startswith("__"))
    record("E 迁移", "migrations/versions 恰为 0001_initial_schema",
           versions == ["0001_initial_schema.py"], repr(versions))
    migration_text = _read("migrations/versions/0001_initial_schema.py")
    block = _create_table_block(migration_text, "export_job")
    record("E 迁移", "迁移内含 export_job 建表（本批无需新表）", bool(block))
    record("E 迁移", "迁移内 export_job 无 is_deleted 列（冻结：本表无软删）",
           bool(block) and "is_deleted" not in block)
    record("E 迁移", "迁移内 export_job 恰 15 列（冻结）",
           block.count("sa.Column(") == 15, str(block.count("sa.Column(")))


# ══════════════════════════════════════════════════════════════ F 契约
def check_contract() -> None:
    say("[F] 契约：响应结构 / 状态码 / TTL / 幂等 / 分页 / 不外泄")
    svc = _read("app/services/export_service.py")
    api = _read("app/api/v1/exports.py")
    cfg = _read("app/core/config.py")

    record("F 契约", "E-01 成功状态码 = 202（冻结）", "CREATE_STATUS = 202" in api)
    record("F 契约", "E-01 成功文案 = 导出任务已创建", 'CREATE_MESSAGE = "导出任务已创建"' in api)
    record("F 契约", "同步生成：成功即 ready（S1-D §5.3）", 'status="ready"' in svc)
    record("F 契约", "TTL 10 分钟 / purge 60 分钟（冻结）",
           'EXPORT_DOWNLOAD_TTL_MINUTES", 10' in cfg and 'EXPORT_PURGE_MINUTES", 60' in cfg)
    record("F 契约", "会话验密上限 VERIFY_MAX_EXPORT = 3（冻结）",
           'VERIFY_MAX_EXPORT", 3' in cfg)
    record("F 契约", "进行中冲突 409 EXPORT_IN_PROGRESS",
           "ErrorCode.EXPORT_IN_PROGRESS" in svc)
    record("F 契约", "过期 410 EXPORT_EXPIRED", "ErrorCode.EXPORT_EXPIRED" in svc)
    record("F 契约", "非本人 404 RESOURCE_NOT_FOUND", "ErrorCode.RESOURCE_NOT_FOUND" in svc)
    record("F 契约", "二次验密计数 + 达阈值中止（PASSWORD_INVALID / SESSION_VERIFY_ABORTED）",
           "ErrorCode.PASSWORD_INVALID" in svc and "ErrorCode.SESSION_VERIFY_ABORTED" in svc)
    record("F 契约", "验密成功清零 export_pwd_fail_count", "export_pwd_fail_count = 0" in svc)
    record("F 契约", "E-01 支持 Idempotency-Key（复用 core.idempotency）",
           "idempotency.normalize_key" in api and "idempotency.lookup" in api)
    record("F 契约", "E-04 复用游标分页 parse_limit / encode_cursor / decode_cursor",
           all(k in svc for k in ("parse_limit", "encode_cursor", "decode_cursor")))
    record("F 契约", "E-04 排序 created_at DESC（不支持自定义）",
           "ExportJob.created_at.desc()" in svc)
    record("F 契约", "E-03 返回文件流并手工写 X-Request-Id（不走 api_response）",
           "send_file" in api and 'response.headers["X-Request-Id"]' in api)
    record("F 契约", "E-03 Content-Disposition 为冻结形态（服务端生成文件名）",
           "attachment; filename=" in api and "healthtrack_export" in svc)
    # 视图键集合：必须按**字典键**判定，不能按"全文是否出现 file_path"判定 ——
    # ``job_view`` 的 **docstring** 里就写着"永不包含 file_path"，全文扫描必然假 FAIL。
    view_body = svc.split("def job_view")[1].split("def ")[0]
    view_keys = set(re.findall(r'"([a-z_]+)":', view_body))
    expected_keys = {"export_id", "format", "status", "record_count", "file_size_bytes",
                     "download_expires_at", "purge_at", "downloaded_at", "created_at"}
    record("F 契约", "响应视图恰 9 键且**无** file_path（永不外泄）",
           view_keys == expected_keys, repr(sorted(view_keys ^ expected_keys)))
    record("F 契约", "file_token 仅可下载状态下给值（凭证暴露面最小化）",
           'data["file_token"] = job.file_token if status in DOWNLOADABLE_STATUSES else None'
           in svc)
    record("F 契约", "E-04 items 不含 file_token（凭证暴露面最小化）",
           "include_token=False" in svc)

    cols = re.search(r"EXPORT_COLUMNS: Tuple\[str, \.\.\.\] = \(([^)]*)\)", svc)
    flat = re.sub(r"\s+", " ", cols.group(1)) if cols else ""
    record("F 契约", "导出列不含 id / user_id / token",
           "id" not in [c.strip().strip('"') for c in flat.split(",")] and
           '"user_id"' not in flat and '"file_token"' not in flat,
           flat[:160])


# ══════════════════════════════════════════════════════════════ G 安全
def check_security() -> None:
    say("[G] 安全：身份隔离 / 软删过滤 / 路径防护 / 凭证强度")
    svc = _read("app/services/export_service.py")
    api = _read("app/api/v1/exports.py")

    record("G 安全", "取数恒带 user_id 条件", "HealthRecord.user_id == user_id" in svc)
    record("G 安全", "取数恒带 is_deleted == 0", "HealthRecord.is_deleted == 0" in svc)
    record("G 安全", "标签取数恒带 is_deleted == 0", "RecordTag.is_deleted == 0" in svc)
    record("G 安全", "E-02 隔离 WHERE id + user_id",
           "ExportJob.id == export_id" in svc and "ExportJob.user_id == user_id" in svc)
    record("G 安全", "E-03 三条件（id + user_id + file_token）",
           "ExportJob.file_token == token" in svc)
    record("G 安全", "user_id 只来自 Access Token（current_user_id）",
           "current_user_id()" in api and "request.args.get(\"user_id\")" not in api)
    record("G 安全", "目录穿越防护（commonpath 收敛于 EXPORT_DIR）",
           "commonpath" in svc and "realpath" in svc)
    record("G 安全", "凭证 = token_hex(16)（32 位十六进制，匹配 CHAR(32)）",
           "secrets.token_hex(FILE_TOKEN_BYTES)" in svc and "FILE_TOKEN_BYTES = 16" in svc)
    # 「客户端无法指定服务器路径」必须按**客户端入参**判定：``file_path`` 在本批源码中作为
    # **服务端内部字段**合法出现（api 只读 ``job.file_path``、svc 落盘与路径收敛），
    # 把"全文不含 file_path"当判据必然假 FAIL。
    client_path_inputs = ('request.args.get("file_path")', 'request.args["file_path"]',
                          "request.form", 'payload.get("file_path")',
                          'payload["file_path"]')
    record("G 安全", "客户端**无法**指定服务器路径（无 file_path 入参）",
           not any(k in svc or k in api for k in client_path_inputs)
           and 'os.path.join(base, f"{new_file_token()}.{ext}")' in svc)
    record("G 安全", "日志不含健康数值 / 用户名 / user_id / 完整 file_path",
           "logger" in svc and "logger.info" in svc and
           not re.search(r"logger\.[a-z]+\([^)]*file_path", svc))
    # 「不做小范围豁免」= 任务**落库前必须**先过验密闸门。不能用"metric_types 是否出现在
    # verify_password 之前"判定 —— 本批参数校验先于验密执行（合法顺序），该判据必然假 FAIL。
    create_body = svc.split("def create_export")[1]
    gate = create_body.find("if not verify_password(")
    build = create_body.find("ExportJob(")
    record("G 安全", "二次验密为**落库前强制闸门**（无小范围豁免）",
           gate != -1 and build != -1 and gate < build, f"gate={gate} build={build}")
    record("G 安全", "无豁免有行为化用例背书（scope_guard.no_exemption）",
           "test_t_e01_requires_password_no_exemption" in
           (BACKEND / "tests" / "batch6" / "test_batch6_scope_guard.py")
           .read_text(encoding="utf-8"))
    record("G 安全", "本地文件写入限定 export_dir() 且按需建目录",
           "os.makedirs(base, exist_ok=True)" in svc)


# ══════════════════════════════════════════════════════════════ H 交付物 + 红线
def check_deliverables() -> None:
    say("[H] 交付物 + 医疗红线")
    arts = [
        (SCRIPTS / "verify_s2_batch6.py", 300),
        (SCRIPTS / "s2_batch6_http_smoke.py", 300),
        (SCRIPTS / "b6_cleanup_exports.py", 300),
        (SCRIPTS / "s2_batch6_accept.console.txt", 500),
        (SCRIPTS / "s2_batch6_accept.cmd.txt", 100),
        (SCRIPTS / "s2_batch6_accept.sql.txt", 200),
        (PROJECT / "S2_第六批_E01-E04_Edge验收脚本.js", 500),
    ]
    for path, min_size in arts:
        ok = path.is_file() and path.stat().st_size > min_size
        record("H 交付物", f"{path.name} 存在且非空", ok,
               f"{path.stat().st_size} B" if path.is_file() else "缺失")

    tests = sorted(p.name for p in (BACKEND / "tests" / "batch6").glob("test_*.py"))
    record("H 交付物", "tests/batch6 用例文件 ≥ 5", len(tests) >= 5, repr(tests))

    edge = PROJECT / "S2_第六批_E01-E04_Edge验收脚本.js"
    if edge.is_file():
        raw = edge.read_bytes()
        text = edge.read_text(encoding="utf-8")
        record("H 交付物", "Edge 脚本反引号 0（交付链路安全）", raw.count(0x60) == 0,
               f"backtick={raw.count(0x60)}")
        record("H 交付物", "Edge 脚本静态断言点 ≥ 60",
               text.count("ok(") + text.count("okEq(") >= 60,
               str(text.count("ok(") + text.count("okEq(")))

    for rel in BATCH6_FILES:
        path = BACKEND / rel
        text = path.read_text(encoding="utf-8")
        hits = [(n, line.strip()[:100]) for n, line in enumerate(text.splitlines(), 1)
                if not _is_exempt(line) for term in BANNED_TERMS if term in line]
        record("H 交付物", f"红线扫描 {rel} 无医学内容", not hits, repr(hits[:4]))


# ══════════════════════════════════════════════════════════════ F-DB
def _connect(cfg):
    from sqlalchemy import create_engine

    return create_engine(cfg["SQLALCHEMY_DATABASE_URI"])


def check_db() -> None:
    say("[F-DB] 只读连库：结构指纹 + 导出任务卫生")
    from dotenv import load_dotenv
    from sqlalchemy import text

    from app.core.config import load_config

    # ★ 本机事实（本次实测确认，务必保留）：
    #   ``.env.test`` 内的 DB 凭据是**占位值**（MYSQL_USER=CHANGE_ME），而
    #   ``config._load_env_files()`` 对 ``.env.<env>`` 使用 ``override=False``。
    #   本脚本在 [B] 段先执行过 ``create_app("test")``，``os.environ`` 已被占位值占据，
    #   之后 ``load_config("development")`` **无法**覆盖 -> 连库必然
    #   ``1045 Access denied for user 'CHANGE_ME'``（实测复现 2 次）。
    #   故此处显式以 ``override=True`` 重新加载 ``.env.development``：
    #   **仅影响当前进程内存 env**，不写文件、不改密钥、不改任何配置。
    load_dotenv(BACKEND / ".env.development", override=True)
    engine = _connect(load_config("development"))
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).all()]
        record("F-DB", f"表数量 = {EXPECTED_TABLE_COUNT}（8 业务 + 迁移表）",
               len(tables) == EXPECTED_TABLE_COUNT, repr(sorted(tables)))

        # 注意：``information_schema.statistics`` 是**每索引每列一行**，复合索引会占多行；
        # 索引**个数**必须用 ``COUNT(DISTINCT index_name)``（实测裸 COUNT(*) = 28）。
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

        cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'export_job'"
        )).all()}
        record("F-DB", "export_job 列集合 = 冻结 15 列",
               cols == {"id", "user_id", "format", "metric_types", "range_start", "range_end",
                        "status", "file_token", "file_path", "file_size_bytes", "record_count",
                        "download_expires_at", "purge_at", "downloaded_at", "created_at"},
               repr(sorted(cols)))
        record("F-DB", "export_job 不含软删列（冻结）", "is_deleted" not in cols)

        counts = {t: int(conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar() or 0)
                  for t in FROZEN_TABLES}
        say(f"        各表行数：{counts}")
        say(f"        合计：{sum(counts.values())}")
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
    say("S2 第六批 E-01~E-04（数据导出）—— 本批核验（A~H）")
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
