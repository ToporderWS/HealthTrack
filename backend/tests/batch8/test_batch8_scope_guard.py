# -*- coding: utf-8 -*-
"""S2 第八批 A-07 —— 范围守卫 + 医疗红线（**本批不修改历史批次脚本**）。

判据口径：本批权威依据 = ``scripts/verify_s2_batch8.py``。

★ **历史时点差异 + 翻正（2026-09-28 · Test-Baseline-Alignment Batch）**：
``verify_s2_batch7.py`` / ``tests/batch7/test_batch7_scope_guard.py`` 曾把**当时**的接口集合
硬编码并含"**A-07 未注册**"判据；本批实现 A-07 后这些断言**必然 FAIL**，属性**历史时点差异**。
按授权，历史批次与**本文件**的「当时快照」已统一翻正为**当前正式基线**
（42 条接口 / 32 条唯一路径 / 42 条规则 / **13 个蓝图**；``DELETE_ORDER`` 8 → 10）。
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
PROJECT = BACKEND.parent

#: 本批新增接口（1 条接口 / **0 条新路径** —— 复用既有 ``/api/v1/users/me``）
BATCH8_ENDPOINTS = {("DELETE", "/api/v1/users/me")}

#: S2 第七批封板时的 33 条接口（本批**必须全部保留**）
BATCH7_ENDPOINTS = {
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
    ("GET", "/api/v1/records/<int:record_id>"),
    ("PATCH", "/api/v1/records/<int:record_id>"),
    ("DELETE", "/api/v1/records/<int:record_id>"),
    ("POST", "/api/v1/records/batch-delete"),
    ("POST", "/api/v1/goals"),
    ("GET", "/api/v1/goals"),
    ("PATCH", "/api/v1/goals/<int:goal_id>"),
    ("DELETE", "/api/v1/goals/<int:goal_id>"),
    ("POST", "/api/v1/goals/<int:goal_id>/pause"),
    ("POST", "/api/v1/goals/<int:goal_id>/resume"),
    ("GET", "/api/v1/goals/progress"),
    ("GET", "/api/v1/home/overview"),
    ("GET", "/api/v1/stats/trend"),
    ("GET", "/api/v1/stats/summary"),
    ("POST", "/api/v1/exports"),
    ("GET", "/api/v1/exports"),
    ("GET", "/api/v1/exports/<int:export_id>"),
    ("GET", "/api/v1/exports/<int:export_id>/download"),
    ("GET", "/api/v1/me/data/summary"),
    ("POST", "/api/v1/me/data/clear"),
}
#: **当前正式基线**（2026-09-28 翻正；原为 S2 第八批时点 34 / 26 / 34 / 10）
EXPECTED_ENDPOINTS = 42
EXPECTED_PATHS = 32
EXPECTED_RULES_NON_STATIC = 42
EXPECTED_BLUEPRINTS = 13

#: 本批（S2 第八批）之后各批的**合法扩展**（逐批登记）
#:   S4-2 +3（profile/avatar）｜B1 +3（password-reset）｜B3 +2（email/bind）
LATER_ENDPOINTS = {
    ("POST", "/api/v1/auth/email/bind-confirm"),
    ("POST", "/api/v1/auth/email/bind-request"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/verify"),
    ("DELETE", "/api/v1/profile/avatar"),
    ("GET", "/api/v1/profile/avatar"),
    ("POST", "/api/v1/profile/avatar"),
}
LATER_PATHS = {
    "/api/v1/auth/email/bind-confirm",
    "/api/v1/auth/email/bind-request",
    "/api/v1/auth/password-reset/confirm",
    "/api/v1/auth/password-reset/request",
    "/api/v1/auth/password-reset/verify",
    "/api/v1/profile/avatar",
}

#: 本批生产文件（**只允许这 3 个**）
BATCH8_FILES = (
    "app/__init__.py",
    "app/services/account_service.py",
    "app/api/v1/account.py",
)

#: 医疗红线（与历批同口径）
BANNED_TERMS = ("诊断", "确诊", "疾病", "病症", "病情", "病因", "治疗", "治愈",
                "处方", "用药建议", "剂量", "医嘱", "问诊", "医学结论", "建议就医")
#: 运行期中性文案白名单（出现在注释 / 文档串中的说明不属"运行期文案"）
BATCH8_A07_TERMS = ("注销账号", "账号已注销")


def _sets(app):
    rules = [r for r in app.url_map.iter_rules() if not str(r.rule).startswith("/static")]
    endpoints = set()
    paths = set()
    for rule in rules:
        path = str(rule.rule)
        paths.add(path)
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            endpoints.add((method, path))
    return rules, endpoints, paths


def _read(rel: str) -> str:
    return (BACKEND / rel.replace("/", "\\")).read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════
# 路由范围
# ════════════════════════════════════════════════════════════════════
def test_b8_expected_counts(app):
    rules, endpoints, paths = _sets(app)
    assert len(rules) == EXPECTED_RULES_NON_STATIC, sorted(str(r.rule) for r in rules)
    assert len(paths) == EXPECTED_PATHS, sorted(paths)
    assert len(endpoints) == EXPECTED_ENDPOINTS, sorted(endpoints)


def test_b8_new_endpoint_registered(app):
    _rules, endpoints, _paths = _sets(app)
    assert ("DELETE", "/api/v1/users/me") in endpoints


def test_b8_delta_is_exactly_batch8(app):
    """增量 = 本批 1 条接口 ∪ 后续各批合法扩展（登记于 LATER_*）；A-07 复用既有路径。"""
    _rules, endpoints, paths = _sets(app)
    assert endpoints - BATCH7_ENDPOINTS == BATCH8_ENDPOINTS | LATER_ENDPOINTS
    assert len(paths) == EXPECTED_PATHS


def test_b8_previous_batches_all_preserved(app):
    _rules, endpoints, _paths = _sets(app)
    assert BATCH7_ENDPOINTS.issubset(endpoints)


def test_b8_users_me_has_exactly_two_methods(app):
    """``/api/v1/users/me`` 恰两个方法：``GET``（A-06，users 蓝图）+ ``DELETE``（A-07，account 蓝图）。"""
    rules = [r for r in app.url_map.iter_rules() if str(r.rule) == "/api/v1/users/me"]
    methods = set()
    for rule in rules:
        methods |= (rule.methods - {"HEAD", "OPTIONS"})
    assert methods == {"GET", "DELETE"}, methods
    endpoints = {r.endpoint for r in rules}
    assert endpoints == {"users.get_me", "account.close_current_account"}, endpoints


def test_b8_no_out_of_scope_modules(app):
    """不得注册本批范围之外的蓝图（预期 10 个，且 ``account`` 必须在内）。"""
    names = set(app.blueprints.keys())
    # ★ 翻正：S4-2 → avatar；B1 → password_reset；B3 → email_bind
    assert names == {"account", "auth", "avatar", "data", "email_bind", "exports",
                     "goals", "health", "password_reset", "profile", "records",
                     "stats", "users"}, sorted(names)
    assert len(names) == EXPECTED_BLUEPRINTS


def test_b8_account_blueprint_registered_in_app():
    src = _read("app/__init__.py")
    assert "from app.api.v1.account import bp as account_bp" in src
    assert "app.register_blueprint(account_bp, url_prefix=API_V1_PREFIX)" in src
    assert src.count("app.register_blueprint(") == EXPECTED_BLUEPRINTS


def test_b8_endpoint_requires_auth(client):
    resp = client.delete("/api/v1/users/me", json={"password": "x", "confirm_text": "注销账号"})
    assert resp.status_code == 401, resp.get_json()
    assert resp.get_json()["code"] == "UNAUTHENTICATED"


def test_b8_user_id_only_from_token():
    """``user_id`` 只能由服务端从 Token 解析；客户端提交路径不存在。"""
    src = _read("app/api/v1/account.py")
    assert "current_user_id()" in src
    for forbidden in ('request.args.get("user_id")', "request.json[\"user_id\"]",
                      "request.form.get(\"user_id\")", 'request.get_json().get("user_id")'):
        assert forbidden not in src


# ════════════════════════════════════════════════════════════════════
# 服务层契约（按源码口径判定）
# ════════════════════════════════════════════════════════════════════
def test_b8_no_scope_expansion_params_read():
    """**不接受**范围扩展参数：源码中不得以客户端入参方式读取这些键。"""
    src = _read("app/services/account_service.py")
    for term in ("target_user_id", "grace_period", "defer", "schedule", "force",
                 "include_profile_row", "delete_account", "include_sessions"):
        for pattern in (f'.get("{term}")', f"['{term}']", f'["{term}"]'):
            assert pattern not in src, (term, pattern)


def test_b8_confirm_text_is_independent_constant():
    """C1：确认文字必须是 **A-07 独立常量**「注销账号」，**不得**复用 D-02 的「确认删除」。

    判定口径取**字面值引用**（带引号），避免误伤文档串中对契约的说明文字。
    """
    src = _read("app/services/account_service.py")
    assert 'CONFIRM_TEXT = "注销账号"' in src
    assert '"确认删除"' not in src
    assert "record_service.CONFIRM_TEXT" not in src
    assert 'CONFIRM_TEXT = record_service' not in src


def test_b8_success_data_is_single_key():
    """C3：成功 ``data`` 恰 1 键 ``account_closed``；无 warning / soft_warning 字段。"""
    src = _read("app/services/account_service.py")
    assert 'CLOSED_DATA: Dict[str, Any] = {"account_closed": True}' in src
    assert '"soft_warning"' not in src
    assert '"warnings"' not in src
    assert "soft_warning=" not in src


def test_b8_delete_order_is_frozen():
    """★ T2 删除顺序冻结（账号最后；``record_tag`` 先于 ``health_record``）。"""
    src = _read("app/services/account_service.py")
    block = src.split("DELETE_ORDER: Tuple[str, ...] = (")[1].split(")")[0]
    # 元组内的说明性注释不参与语义（B2 扩展在同一元组内加入了注释行）
    block = "".join(ln.split("#", 1)[0] for ln in block.splitlines())
    order = [seg.strip().strip('",') for seg in block.replace("\n", "").split(",") if seg.strip()]
    # ★ 翻正：B2（CR-F006-001 §九）把 DELETE_ORDER 由 8 扩为 10，原 6 表顺序未动、账号仍在最后
    assert order == ["record_tag", "health_record", "health_goal", "user_profile",
                     "export_job", "user_session", "login_failure_state",
                     "verification_code", "password_reset_token", "user_account"], order
    # 源码中 8 次 _purge 的先后次序必须与冻结顺序一致
    body = src.split("def close_account(")[1]
    positions = [body.index(f'counts["{name}"]') for name in order]
    assert positions == sorted(positions), positions


def test_b8_single_transaction_and_rollback():
    """★ 单事务：``close_account`` 内 **恰 1 次 commit** + 异常路径 rollback + 自检先于 commit。"""
    body = _read("app/services/account_service.py").split("def close_account(")[1]
    assert body.count("db.commit()") == 1
    assert "db.rollback()" in body
    assert body.index("_assert_no_residue(") < body.index("db.commit()")


def test_b8_password_gate_precedes_writes():
    """密码校验（T0）必须**先于**任何删除写操作。"""
    body = _read("app/services/account_service.py").split("def close_account(")[1]
    assert body.index("_verify_login_password(") < body.index('counts["record_tag"]')


def test_b8_never_reads_soft_delete_window():
    """★ R-13 核心：实现**不得**读取 ``deleted_at`` / 30 天窗口做过滤。

    判定按**代码表达式**口径（排除文档串中对契约的说明）。
    """
    src = _read("app/services/account_service.py")
    for pattern in ("SOFT_DELETE_PURGE_DAYS", "purge_days",
                    "HealthRecord.deleted_at", "RecordTag.deleted_at",
                    "HealthGoal.deleted_at", "UserProfile.deleted_at",
                    ".is_deleted ==", ".is_deleted=", "deleted_at >", "deleted_at <",
                    "timedelta(days=30)"):
        assert pattern not in src, pattern


def test_b8_file_ops_outside_transaction():
    """★ T4：文件删除在 ``db.commit()`` **之后**（禁止在事务内删除文件）。"""
    body = _read("app/services/account_service.py").split("def close_account(")[1]
    assert body.index("db.commit()") < body.index("_cleanup_export_files(")


def test_b8_no_new_error_codes_used():
    """不新增错误码：仅复用既定全局码与既定字段级码。"""
    src = _read("app/services/account_service.py")
    used = set(re.findall(r"(?<!Field)ErrorCode\.([A-Z_]+)", src))
    assert used <= {"INVALID_PARAM", "UNAUTHENTICATED", "PASSWORD_INVALID",
                    "VALIDATION_FAILED", "INTERNAL_ERROR"}, used
    field_codes = set(re.findall(r"FieldErrorCode\.([A-Z_]+)", src))
    assert field_codes <= {"REQUIRED", "INVALID_FORMAT"}, field_codes


def test_b8_no_new_tables_or_migrations():
    """本批**不得**新增表 / 迁移（重试登记为落盘 JSONL，**不入业务库**）。"""
    src = _read("app/services/account_service.py")
    assert "__tablename__" not in src
    assert "op.create_table" not in src
    assert "cleanup_retry.jsonl" in src
    # ★ 翻正：本批（S2 第八批）不得新增；0002 由 S4-2（头像）、0003 由 B1（密码找回）合法引入
    migrations = sorted(p.name for p in (BACKEND / "migrations" / "versions").glob("*.py"))
    assert migrations == ["0001_initial_schema.py", "0002_user_profile_avatar.py",
                          "0003_password_reset_email.py"], migrations


def test_b8_redline_scan_production_files():
    for rel in BATCH8_FILES:
        src = _read(rel)
        for term in BANNED_TERMS:
            assert term not in src, (rel, term)


def test_b8_runtime_texts_are_neutral():
    src = _read("app/services/account_service.py")
    for term in BATCH8_A07_TERMS:
        assert term in src
