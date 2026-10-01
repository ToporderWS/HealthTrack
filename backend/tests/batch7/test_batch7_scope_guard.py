# -*- coding: utf-8 -*-
"""S2 第七批 —— 范围守卫 + 医疗红线（**本批不修改历史批次脚本**）。

判据口径：本批权威依据 = ``scripts/verify_s2_batch7.py``；
历史批次（batch5 / batch6）守卫脚本把它们**当时**的接口集合**硬编码**，
本批新增 ``D-01`` / ``D-02`` 后历史守卫必然 FAIL —— 属**历史时点判据**。

★ **翻正（2026-09-28 · Test-Baseline-Alignment Batch）**：历史批次与**本文件**的
「当时快照」已按授权统一翻正为**当前正式基线**（42 条接口 / 32 条唯一路径）；
本文件 ``EXPECTED_ENDPOINTS`` / ``EXPECTED_PATHS`` 由 **33 / 26 → 42 / 32**，
``test_b7_a07_not_registered`` 翻正为 ``test_b7_a07_registered_by_batch8``。
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
PROJECT = BACKEND.parent

#: 本批新增接口（2 条接口 / 2 条唯一路径）
BATCH7_ENDPOINTS = {
    ("GET", "/api/v1/me/data/summary"),
    ("POST", "/api/v1/me/data/clear"),
}
BATCH7_PATHS = {"/api/v1/me/data/summary", "/api/v1/me/data/clear"}

#: S2 第六批封板时的 31 条接口（本批**必须全部保留**）
BATCH6_ENDPOINTS = {
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
}
#: **当前正式基线**（2026-09-28 翻正；原为 S2 第七批时点 33 / 26）
EXPECTED_ENDPOINTS = 42
EXPECTED_PATHS = 32

#: 本批（S2 第七批）之后各批的**合法扩展**（逐批登记）
#:   b8 +1（A-07 DELETE users/me）｜S4-2 +3（profile/avatar）｜B1 +3（password-reset）｜B3 +2（email/bind）
LATER_ENDPOINTS = {
    ("POST", "/api/v1/auth/email/bind-confirm"),
    ("POST", "/api/v1/auth/email/bind-request"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/verify"),
    ("DELETE", "/api/v1/profile/avatar"),
    ("GET", "/api/v1/profile/avatar"),
    ("POST", "/api/v1/profile/avatar"),
    ("DELETE", "/api/v1/users/me"),
}
#: （A-07 ``DELETE /api/v1/users/me`` **复用**第二批既有路径 ⇒ **不**计入「新增路径」）
LATER_PATHS = {
    "/api/v1/auth/email/bind-confirm",
    "/api/v1/auth/email/bind-request",
    "/api/v1/auth/password-reset/confirm",
    "/api/v1/auth/password-reset/request",
    "/api/v1/auth/password-reset/verify",
    "/api/v1/profile/avatar",
}

#: 本批生产文件
BATCH7_FILES = (
    "app/__init__.py",
    "app/services/data_service.py",
    "app/api/v1/data.py",
)

#: 医疗红线（与历批同口径）
BANNED_TERMS = ("诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药",
                "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围",
                "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数")
EXEMPT_MARKERS = ("禁止", "不得", "不含", "不涉及", "非医疗", "非医学", "中性", "无医学",
                  "不做", "严禁", "banned", "禁用", "红线", "豁免")


def _sets(app):
    """从**已初始化**的应用实例读取路由集合（不新建 app，避免污染进程 env）。"""
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = {(m, str(r)) for r in rules for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}
    return rules, paths, endpoints


def _read(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8")


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in EXEMPT_MARKERS)


# ════════════════════════════════════════════════════════════════════
# 范围
# ════════════════════════════════════════════════════════════════════
def test_b7_expected_counts(app):
    """接口 42 / 唯一路径 32（**当前正式基线**）。"""
    _rules, paths, endpoints = _sets(app)
    assert len(endpoints) == EXPECTED_ENDPOINTS, len(endpoints)
    assert len(paths) == EXPECTED_PATHS, sorted(paths)


def test_b7_new_endpoints_registered(app):
    """D-01 / D-02 均已注册，且各占 **1 条唯一路径**。"""
    _rules, paths, endpoints = _sets(app)
    assert BATCH7_ENDPOINTS <= endpoints, sorted(BATCH7_ENDPOINTS - endpoints)
    assert BATCH7_PATHS <= paths
    assert len(BATCH7_PATHS) == 2 and len(BATCH7_ENDPOINTS) == 2


def test_b7_delta_is_exactly_batch7(app):
    """增量 = 本批 D-01 / D-02 ∪ 后续各批合法扩展（登记于 LATER_*）。"""
    _rules, _paths, endpoints = _sets(app)
    extra = endpoints - BATCH6_ENDPOINTS
    expected = BATCH7_ENDPOINTS | LATER_ENDPOINTS
    assert extra == expected, sorted(extra - expected)


def test_b7_previous_batches_all_preserved(app):
    """S2 第二~六批的 31 条接口**全部保留**（未被删改）。"""
    _rules, _paths, endpoints = _sets(app)
    missing = BATCH6_ENDPOINTS - endpoints
    assert not missing, sorted(missing)
    assert len(BATCH6_ENDPOINTS) == 31


def test_b7_a07_registered_by_batch8(app):
    """★ 翻正：A-07（``DELETE /api/v1/users/me``）已由 **S2 第八批封板**正式注册。"""
    rules, _paths, endpoints = _sets(app)
    assert ("DELETE", "/api/v1/users/me") in endpoints
    assert [r for r in rules if str(r) == "/api/v1/users/me"
            and "DELETE" in (r.methods or set())] != []


def test_b7_no_out_of_scope_modules(app):
    """第八批 / 越界模块**均未注册**（提醒 / 通知 / 管理 / 支付 / 会员）。"""
    _rules, paths, _endpoints = _sets(app)
    forbidden = ("/api/v1/reminders", "/api/v1/notifications", "/api/v1/admin",
                 "/api/v1/payments", "/api/v1/membership", "/api/v1/export-admin")
    hits = sorted(p for p in paths for f in forbidden if p.startswith(f))
    assert not hits, hits


def test_b7_data_module_scope_is_exactly_two_paths(app):
    """``/me/data/*`` 下**只有** D-01 / D-02 两条路径。"""
    _rules, paths, _endpoints = _sets(app)
    mine = sorted(p for p in paths if p.startswith("/api/v1/me/data"))
    assert mine == sorted(BATCH7_PATHS), mine


# ════════════════════════════════════════════════════════════════════
# 鉴权
# ════════════════════════════════════════════════════════════════════
def test_b7_both_endpoints_require_auth(client):
    """D-01 / D-02 **均需鉴权**：无 Token → ``401``。"""
    summary = client.get("/api/v1/me/data/summary")
    assert summary.status_code == 401, summary.get_json()
    assert summary.get_json()["code"] == "UNAUTHENTICATED"

    clear = client.post("/api/v1/me/data/clear", json={
        "confirm_text": "确认删除", "password": "x", "acknowledge_irreversible": True,
    })
    assert clear.status_code == 401, clear.get_json()
    assert clear.get_json()["code"] == "UNAUTHENTICATED"


def test_b7_data_blueprint_registered_in_app():
    """``app/__init__.py`` 以**纯追加**方式注册 data 蓝图（既有注册顺序不变）。"""
    text = _read("app/__init__.py")
    assert "from app.api.v1.data import bp as data_bp" in text
    assert "app.register_blueprint(data_bp, url_prefix=API_V1_PREFIX)" in text
    # ★ 翻正：9（S2 第七批时点）→ 13（+avatar / +account / +email_bind / +password_reset）
    assert text.count("register_blueprint") == 13, text.count("register_blueprint")


# ════════════════════════════════════════════════════════════════════
# 隔离 / 无豁免
# ════════════════════════════════════════════════════════════════════
def test_b7_user_id_only_from_token():
    """源码口径：``user_id`` 只能来自 Token（视图不读 query / body / 路径中的 user_id）。"""
    api = _read("app/api/v1/data.py")
    assert "current_user_id()" in api
    for bad in ('request.args.get("user_id")', 'request.args["user_id"]',
                'request.form["user_id"]', 'payload.get("user_id")',
                'body.get("user_id")', 'session["user_id"]'):
        assert bad not in api, bad


def test_b7_no_scope_expansion_params_in_source():
    """**不接受**范围扩展参数（``include_profile_row`` / ``delete_account`` 等）。

    判定按**客户端入参读取**口径：源码 docstring 中**可以**声明"不接受某参数"
    （这正是冻结契约的要求），但**不得**出现读取该参数的代码
    （``.get("<term>")`` / ``["<term>"]``）。
    """
    src = _read("app/services/data_service.py") + _read("app/api/v1/data.py")
    for term in ("include_profile_row", "delete_account", "include_sessions", "purge_all"):
        assert f'.get("{term}")' not in src, term
        assert f"['{term}']" not in src, term
        assert f'["{term}"]' not in src, term


def test_b7_clear_uses_single_transaction_and_rollback():
    """D-02 **单事务** + 异常 ``rollback`` + ``500``（不得清一半）。"""
    src = _read("app/services/data_service.py")
    body = src.split("def clear_all_data")[1]
    assert body.count("db.commit()") == 1, body.count("db.commit()")
    assert "db.rollback()" in body
    assert "ErrorCode.INTERNAL_ERROR" in body
    # 密码闸门必须先于任何写操作
    assert body.find("_verify_login_password(") < body.find("_soft_delete_records(")


def test_b7_clear_never_touches_protected_tables():
    """D-02 **不得**触碰账号 / 档案行 / 会话 / 登录失败 / 导出任务。"""
    src = _read("app/services/data_service.py")
    body = src.split("def clear_all_data")[1]
    for forbidden in ("delete(UserAccount", "delete(UserSession",
                      "delete(ExportJob", "delete(LoginFailureState",
                      "delete(UserProfile"):
        assert forbidden not in body, forbidden
    # 档案只做字段级置空
    assert "setattr(profile, field, None)" in src
    assert "PROFILE_HEALTH_FIELDS" in src


def test_b7_d01_filters_soft_deleted():
    """D-01 恒带 ``is_deleted == 0``（软删数据不计入）。"""
    src = _read("app/services/data_service.py")
    summary_body = src.split("def summary")[1].split("def clear_message")[0]
    assert "HealthRecord.is_deleted == 0" in summary_body
    assert "HealthGoal.is_deleted == 0" in src


# ════════════════════════════════════════════════════════════════════
# 医疗红线（生产文件不得出现医学内容）
# ════════════════════════════════════════════════════════════════════
def test_b7_redline_scan_production_files():
    """本批生产文件**无医学内容**（含豁免行口径与历批一致）。"""
    for rel in BATCH7_FILES:
        text = _read(rel)
        hits = [
            (n, line.strip()[:100])
            for n, line in enumerate(text.splitlines(), 1)
            if not _is_exempt(line)
            for term in BANNED_TERMS if term in line
        ]
        assert not hits, (rel, hits[:4])


def test_b7_redline_runtime_texts_are_neutral(client, rich_user):
    """运行期文案**中性**（不含医学判断 / 建议）。"""
    from tests.batch7.conftest import clear, confirm_payload, summary

    texts = [
        summary(client, rich_user["header"]).get_data(as_text=True),
        clear(client, rich_user["header"],
              **confirm_payload(rich_user["password"])).get_data(as_text=True),
    ]
    blob = " ".join(texts)
    for term in BANNED_TERMS:
        assert term not in blob, term


def test_b7_d01_response_has_no_health_values(client, rich_user):
    """D-01 响应**不含任何健康数值**（数值统计属趋势页 S-03）。"""
    from tests.batch7.conftest import summary

    data = summary(client, rich_user["header"]).get_json()["data"]
    blob = str(data)
    for term in ("value_1", "value_2", "value_3", "unit", "attr_1", "note"):
        assert term not in blob, term
