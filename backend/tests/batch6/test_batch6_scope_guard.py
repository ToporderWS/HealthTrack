# -*- coding: utf-8 -*-
"""S2 第六批 T（范围守卫）+ 医疗红线扫描 + 文件清单自证。

覆盖验收项：
- T：接口集合恰为 Y-01 + A-01~A-06 + P-01/P-02 + R-01~R-08 + G-01~G-07 + S-01~S-03 + E-01~E-04
  （**共 31 条接口 / 24 条唯一路径**）；**不含** D-01/D-02、A-07、提醒 / 管理 / 支付 接口；
- 结构性证据：前五批 27 条接口**全部保留**，新增**恰为** E-01~E-04 共 4 条接口 / 3 条路径；
- 红线：本批源码、注释、文案不含医学内容。

> ★ **翻正（2026-09-28 · Test-Baseline-Alignment Batch）**：原名 ``EXPECTED_ENDPOINTS``
> 为 **S2 第六批时点快照（31 条 / 24 路径）**；后续各批（b7/b8 / S4-2 / B1 / B3）的
> **合法扩展**使其必然 FAIL —— 属**历史时点判据**。本批按授权翻正为**当前正式基线**
> （:data:`CURRENT_ENDPOINTS` = 42 条 / 32 路径），逐批登记 :data:`LATER_ENDPOINTS`。

**路径数事实**：E-01 与 E-04 **共用** ``/api/v1/exports``（POST / GET 各一条接口），
故新增 **4 条接口 / 3 条唯一路径** ⇒ 路径 **21 → 24**、接口 **27 → 31**。
（若按「接口 × 路径」计数则为 25，但本项目既有口径为 **rule 字符串去重**，故记为 24。）
"""
from __future__ import annotations

from pathlib import Path

from tests.batch6.conftest import (
    body_of,
    download,
    export_detail,
    list_exports,
    new_export,
)

BACKEND = Path(__file__).resolve().parents[2]

#: 本批新增 / 修改的生产代码（相对 backend/）
BATCH6_FILES = (
    "app/__init__.py",
    "app/services/export_service.py",
    "app/api/v1/exports.py",
)

#: 红线禁用词（与前五批一致，**不得放宽**）—— 本行即禁用词清单，属约束声明行
BANNED_TERMS = ("诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药", "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围", "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数")  # noqa: E501  红线声明行

#: 豁免标记：出现任一即视为「约束声明」，不判为医学内容
EXEMPT_MARKERS = (
    "禁止", "不得", "不含", "不涉及", "非医疗", "非医学", "中性", "无医学",
    "不做", "严禁", "banned", "禁用", "红线", "豁免",
)

#: 第二批留存（7 条接口 / 7 条路径）
BATCH2_ENDPOINTS = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("PUT", "/api/v1/auth/password"),
    ("GET", "/api/v1/users/me"),
}
BATCH2_PATHS = {p for _m, p in BATCH2_ENDPOINTS}

#: 第三批新增（10 条接口 / 6 条路径）
BATCH3_ENDPOINTS = {
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
BATCH3_PATHS = {p for _m, p in BATCH3_ENDPOINTS}

#: 第四批新增（7 条接口 / 5 条路径）
BATCH4_NEW_ENDPOINTS = {
    ("GET", "/api/v1/goals"),
    ("POST", "/api/v1/goals"),
    ("GET", "/api/v1/goals/progress"),
    ("PATCH", "/api/v1/goals/<int:goal_id>"),
    ("DELETE", "/api/v1/goals/<int:goal_id>"),
    ("POST", "/api/v1/goals/<int:goal_id>/pause"),
    ("POST", "/api/v1/goals/<int:goal_id>/resume"),
}
BATCH4_NEW_PATHS = {p for _m, p in BATCH4_NEW_ENDPOINTS}

#: 第五批新增（3 条接口 / 3 条路径）
BATCH5_NEW_ENDPOINTS = {
    ("GET", "/api/v1/home/overview"),
    ("GET", "/api/v1/stats/trend"),
    ("GET", "/api/v1/stats/summary"),
}
BATCH5_NEW_PATHS = {p for _m, p in BATCH5_NEW_ENDPOINTS}

#: 本批新增（**4 条接口 / 3 条路径**）
BATCH6_NEW_ENDPOINTS = {
    ("POST", "/api/v1/exports"),
    ("GET", "/api/v1/exports"),
    ("GET", "/api/v1/exports/<int:export_id>"),
    ("GET", "/api/v1/exports/<int:export_id>/download"),
}
BATCH6_NEW_PATHS = {p for _m, p in BATCH6_NEW_ENDPOINTS}

PREVIOUS_ENDPOINTS = (
    BATCH2_ENDPOINTS | BATCH3_ENDPOINTS | BATCH4_NEW_ENDPOINTS | BATCH5_NEW_ENDPOINTS
)
PREVIOUS_PATHS = {p for _m, p in PREVIOUS_ENDPOINTS}

#: S2 第六批完成时点的快照（**原样保留为历史证据**）
EXPECTED_ENDPOINTS = PREVIOUS_ENDPOINTS | BATCH6_NEW_ENDPOINTS
EXPECTED_PATHS = {p for _m, p in EXPECTED_ENDPOINTS}

#: 本批之后各批的**合法扩展**（逐批登记；来源：各批封板报告 / 本批审计表）
#:   b7 +2（me/data）｜b8 +1（A-07）
#:   S4-2 +3（profile/avatar）｜B1 +3（password-reset）｜B3 +2（email/bind）
LATER_ENDPOINTS = {
    ("POST", "/api/v1/auth/email/bind-confirm"),
    ("POST", "/api/v1/auth/email/bind-request"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/verify"),
    ("POST", "/api/v1/me/data/clear"),
    ("GET", "/api/v1/me/data/summary"),
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
    "/api/v1/me/data/clear",
    "/api/v1/me/data/summary",
    "/api/v1/profile/avatar",
}

#: **当前正式基线**（V1.0 前冻结口径）= 本批快照 ∪ 后续各批合法扩展
CURRENT_ENDPOINTS = EXPECTED_ENDPOINTS | LATER_ENDPOINTS
CURRENT_PATHS = {p for _m, p in CURRENT_ENDPOINTS}


def _actual(app):
    rules = [r for r in app.url_map.iter_rules() if str(r).startswith("/api/")]
    paths = {str(r) for r in rules}
    endpoints = {(m, str(r)) for r in rules for m in (r.methods or set()) - {"HEAD", "OPTIONS"}}
    return paths, endpoints


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(marker.lower() in low for marker in EXEMPT_MARKERS)


# ════════════════════════════════════════════════════════════════════
# T —— 范围守卫
# ════════════════════════════════════════════════════════════════════
def test_t_expected_counts():
    """T：契约自检 —— 31 条接口 / 24 条路径（27+4 接口；21+3 路径）。"""
    assert len(BATCH2_ENDPOINTS) == 7
    assert len(BATCH3_ENDPOINTS) == 10
    assert len(BATCH4_NEW_ENDPOINTS) == 7
    assert len(BATCH5_NEW_ENDPOINTS) == 3
    assert len(BATCH6_NEW_ENDPOINTS) == 4
    assert len(EXPECTED_ENDPOINTS) == 31
    assert len(BATCH2_PATHS) == 7 and len(BATCH3_PATHS) == 6
    assert len(BATCH4_NEW_PATHS) == 5 and len(BATCH5_NEW_PATHS) == 3
    assert len(BATCH6_NEW_PATHS) == 3
    assert len(EXPECTED_PATHS) == 24


def test_t_endpoint_set_matches_current_phase(app):
    """T：接口集合 = 当前阶段允许集合（不多不少）。"""
    _paths, endpoints = _actual(app)
    assert endpoints == CURRENT_ENDPOINTS, f"接口集合差异：{endpoints ^ CURRENT_ENDPOINTS}"


def test_t_path_set_matches_current_phase(app):
    """T：路径集合 = 当前阶段允许集合（21 → 24）。"""
    paths, _endpoints = _actual(app)
    assert paths == CURRENT_PATHS, f"路径集合差异：{paths ^ CURRENT_PATHS}"


def test_t_previous_batches_all_preserved(app):
    """T（结构性证据）：前五批 27 条接口**全部保留**（无删除 / 无改名）。"""
    _paths, endpoints = _actual(app)
    missing = PREVIOUS_ENDPOINTS - endpoints
    assert not missing, f"既有接口被移除：{sorted(missing)}"


def test_t_delta_is_exactly_batch6(app):
    """T（结构性证据）：Δ = 本批 E-01~E-04 ∪ 后续各批合法扩展（登记于 LATER_*）。"""
    paths, endpoints = _actual(app)
    assert endpoints - PREVIOUS_ENDPOINTS == BATCH6_NEW_ENDPOINTS | LATER_ENDPOINTS
    assert paths - PREVIOUS_PATHS == BATCH6_NEW_PATHS | LATER_PATHS


def test_t_no_out_of_scope_modules_registered(app):
    """T：**V1.0 明确不做**的模块仍不得注册（D-01/D-02、A-07 已由后续批次正式纳入）。"""
    forbidden_prefixes = (
        "/api/v1/reminders",      # 提醒（纯本地，零 API）
        "/api/v1/notifications",  # 通知（V1.0 不做）
        "/api/v1/admin",          # 无管理后台
        "/api/v1/payments",       # 支付（V1.0 不做）
        "/api/v1/membership",     # 会员（V1.0 不做）
    )
    paths = {str(r) for r in app.url_map.iter_rules()}
    for prefix in forbidden_prefixes:
        assert not any(p.startswith(prefix) for p in paths), f"越界接口：{prefix}"

    # ★ 翻正：A-07（S2 第八批封板）已正式纳入 → 断言由「不得出现」翻正为「必须已注册」
    delete_me = [r for r in app.url_map.iter_rules()
                 if str(r) == "/api/v1/users/me" and "DELETE" in (r.methods or set())]
    assert delete_me, "A-07 注销接口（S2 第八批封板）应已注册"


def test_t_export_routes_are_all_authenticated(client):
    """T：E-01~E-04 全部需要鉴权（未登录 → 401，**无豁免**）。"""
    assert client.post("/api/v1/exports", json={"format": "csv", "password": "x"}).status_code == 401
    assert client.get("/api/v1/exports").status_code == 401
    assert client.get("/api/v1/exports/1").status_code == 401
    assert client.get("/api/v1/exports/1/download?file_token=abc").status_code == 401


def test_t_e01_requires_password_no_exemption(client, user):
    """T：E-01 **无小范围豁免** —— 即便 ``metric_types`` 极窄，依旧必须验密。"""
    resp = client.post("/api/v1/exports", headers=user["header"],
                       json={"format": "csv", "metric_types": ["weight"]})
    body = body_of(resp, 400)
    assert body["code"] == "INVALID_PARAM"
    assert any(e.get("field") == "password" for e in (body.get("errors") or [])), body


# ════════════════════════════════════════════════════════════════════
# 医疗红线 —— 源码 / 注释
# ════════════════════════════════════════════════════════════════════
def test_redline_source_scan():
    """红线-1：本批生产代码不含医学内容（声明句豁免）。"""
    assert len(BATCH6_FILES) == 3
    hits = []
    scanned = 0
    for rel in BATCH6_FILES:
        path = BACKEND / rel
        assert path.is_file(), f"待扫描文件不存在：{rel}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            scanned += 1
            if _is_exempt(line):
                continue
            for term in BANNED_TERMS:
                if term in line:
                    hits.append(f"{rel}:{lineno} 命中「{term}」：{line.strip()[:120]}")
    assert scanned > 300, f"扫描行数异常（{scanned}）"
    assert not hits, "判定命中：\n" + "\n".join(hits)


def test_redline_no_medical_interpretation_fields():
    """红线-2：本批生产代码**不含**任何医学解释字段名。"""
    banned_keys = ("diagnosis", "advice", "suggestion", "risk_level", "risk",
                   "health_score", "conclusion", "recommendation", "abnormal")
    hits = []
    for rel in BATCH6_FILES:
        path = BACKEND / rel
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _is_exempt(line):
                continue
            for key in banned_keys:
                if f'"{key}"' in line or f"'{key}'" in line:
                    hits.append(f"{rel}:{lineno} 「{key}」")
    assert not hits, hits


def test_redline_runtime_texts_are_neutral(client, user):
    """红线-3：E 接口运行期文案（错误 / 提示）中性，无评价 / 医学词。"""
    samples = [
        client.post("/api/v1/exports", headers=user["header"],
                    json={"format": "csv", "password": user["password"]}),
        client.post("/api/v1/exports", headers=user["header"],
                    json={"format": "xml", "password": user["password"]}),
        client.post("/api/v1/exports", headers=user["header"], json={"format": "csv"}),
        client.post("/api/v1/exports", headers=user["header"],
                    json={"format": "csv", "password": "wrong1234"}),
        export_detail(client, user["header"], 999999),
        download(client, user["header"], 999999, "deadbeef"),
        list_exports(client, user["header"]),
        list_exports(client, user["header"], limit=7),
        list_exports(client, user["header"], cursor="not-a-cursor"),
        client.get("/api/v1/exports"),
    ]
    for resp in samples:
        body = resp.get_json()
        assert body is not None, resp.status_code
        text = body.get("message") or ""
        for term in BANNED_TERMS:
            assert term not in text, f"运行期文案命中「{term}」：{text}"


def test_redline_payload_has_no_interpretation(client, user):
    """红线-4：E-01/E-02/E-04 载荷**不含**医学解释字段与评价文案。"""
    data = new_export(client, user["header"], format="json", password=user["password"])
    payloads = [
        data,
        export_detail(client, user["header"], int(data["export_id"])).get_json()["data"],
        list_exports(client, user["header"]).get_json()["data"],
    ]
    banned_keys = ("diagnosis", "advice", "suggestion", "risk", "risk_level",
                   "health_score", "conclusion", "recommendation", "abnormal")

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key.lower() not in banned_keys, f"{path}.{key} 为医学解释字段"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    for payload in payloads:
        walk(payload)
        assert "未设" not in str(payload)


def test_batch6_files_are_readable_utf8():
    """红线-5：本批文件均为 UTF-8 且非空（防止扫描被绕过）。"""
    for rel in BATCH6_FILES:
        text = (BACKEND / rel).read_text(encoding="utf-8")
        assert len(text) > 200, f"{rel} 内容异常"
