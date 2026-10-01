# -*- coding: utf-8 -*-
"""S2 第四批 T（范围守卫）+ 医疗红线扫描 + 文件清单自证。

覆盖验收项：
- T：接口集合恰为 Y-01 + A-01~A-06 + P-01/P-02 + R-01~R-08 + G-01~G-07（**共 24 条**）；
  **不含** S / E / D / A-07 / P1 / P2 及任何超出 S0 冻结编号的功能接口；
- 结构性证据：第三批 17 条接口**全部保留**，新增**恰为** G-01~G-07 共 7 条；
- 红线：本批源码、注释、文案不含医学内容。

> ★ **翻正（2026-09-28 · Test-Baseline-Alignment Batch）**：原名 ``EXPECTED_ENDPOINTS``
> 为 **S2 第四批时点快照（24 条 / 18 路径）**；后续各批（b5~b8 / S4-2 / B1 / B3）的
> **合法扩展**使其必然 FAIL —— 属**历史时点判据**。本批按授权翻正为**当前正式基线**
> （:data:`CURRENT_ENDPOINTS` = 42 条 / 32 路径），逐批登记 :data:`LATER_ENDPOINTS`。

**路径数事实说明（相对开工方案的事实纠正）**：开工方案 §八推断"13 → 19 条路径"，
实测为 **13 → 18 条路径**。原因：G-01~G-07 共 **7 个接口**映射到 **5 条路径**
（``/goals`` 承载 GET+POST；``/goals/<int:goal_id>`` 承载 PATCH+DELETE；
``/goals/progress`` / ``/goals/<int:goal_id>/pause`` / ``/goals/<int:goal_id>/resume`` 各 1）。
接口数 24 = 17 + 7 与冻结契约完全一致。
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

#: 本批新增 / 修改的生产代码（相对 backend/）
BATCH4_FILES = (
    "app/__init__.py",
    "app/schemas/base.py",
    "app/schemas/goal.py",
    "app/services/goal_service.py",
    "app/services/goal_progress.py",
    "app/api/v1/goals.py",
)

#: 红线禁用词（与第二批 / 第三批一致，**不得放宽**）—— 本行即禁用词清单，属约束声明行
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

#: 本批新增（**7 条接口 / 5 条路径**）
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

#: S2 第四批完成时点的快照（**原样保留为历史证据**）
EXPECTED_ENDPOINTS = BATCH2_ENDPOINTS | BATCH3_ENDPOINTS | BATCH4_NEW_ENDPOINTS
EXPECTED_PATHS = {p for _m, p in EXPECTED_ENDPOINTS}

#: 本批之后各批的**合法扩展**（逐批登记；来源：各批封板报告 / 本批审计表）
#:   b5 +3（stats/home）｜b6 +4（exports）｜b7 +2（me/data）｜b8 +1（A-07）
#:   S4-2 +3（profile/avatar）｜B1 +3（password-reset）｜B3 +2（email/bind）
LATER_ENDPOINTS = {
    ("POST", "/api/v1/auth/email/bind-confirm"),
    ("POST", "/api/v1/auth/email/bind-request"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/verify"),
    ("GET", "/api/v1/exports"),
    ("POST", "/api/v1/exports"),
    ("GET", "/api/v1/exports/<int:export_id>"),
    ("GET", "/api/v1/exports/<int:export_id>/download"),
    ("GET", "/api/v1/home/overview"),
    ("POST", "/api/v1/me/data/clear"),
    ("GET", "/api/v1/me/data/summary"),
    ("DELETE", "/api/v1/profile/avatar"),
    ("GET", "/api/v1/profile/avatar"),
    ("POST", "/api/v1/profile/avatar"),
    ("GET", "/api/v1/stats/summary"),
    ("GET", "/api/v1/stats/trend"),
    ("DELETE", "/api/v1/users/me"),
}
#: （A-07 ``DELETE /api/v1/users/me`` **复用**第二批既有路径 ⇒ **不**计入「新增路径」）
LATER_PATHS = {
    "/api/v1/auth/email/bind-confirm",
    "/api/v1/auth/email/bind-request",
    "/api/v1/auth/password-reset/confirm",
    "/api/v1/auth/password-reset/request",
    "/api/v1/auth/password-reset/verify",
    "/api/v1/exports",
    "/api/v1/exports/<int:export_id>",
    "/api/v1/exports/<int:export_id>/download",
    "/api/v1/home/overview",
    "/api/v1/me/data/clear",
    "/api/v1/me/data/summary",
    "/api/v1/profile/avatar",
    "/api/v1/stats/summary",
    "/api/v1/stats/trend",
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
    """T：契约自检 —— 24 条接口 / 18 条路径（17+7 接口；13+5 路径）。"""
    assert len(BATCH2_ENDPOINTS) == 7
    assert len(BATCH3_ENDPOINTS) == 10
    assert len(BATCH4_NEW_ENDPOINTS) == 7
    assert len(EXPECTED_ENDPOINTS) == 24
    assert len(BATCH2_PATHS) == 7 and len(BATCH3_PATHS) == 6
    assert len(BATCH4_NEW_PATHS) == 5
    assert len(EXPECTED_PATHS) == 18


def test_t_endpoint_set_matches_current_phase(app):
    """T：接口集合 = 当前阶段允许集合（不多不少）。"""
    _paths, endpoints = _actual(app)
    assert endpoints == CURRENT_ENDPOINTS, f"接口集合差异：{endpoints ^ CURRENT_ENDPOINTS}"


def test_t_path_set_matches_current_phase(app):
    """T：路径集合 = 当前阶段允许集合（13 → 18）。"""
    paths, _endpoints = _actual(app)
    assert paths == CURRENT_PATHS, f"路径集合差异：{paths ^ CURRENT_PATHS}"


def test_t_batch3_endpoints_all_preserved(app):
    """T（结构性证据）：第三批 17 条接口**全部保留**（无删除 / 无改名）。"""
    _paths, endpoints = _actual(app)
    missing = (BATCH2_ENDPOINTS | BATCH3_ENDPOINTS) - endpoints
    assert not missing, f"既有接口被移除：{sorted(missing)}"


def test_t_delta_is_exactly_batch4(app):
    """T（结构性证据）：Δ = 本批 G-01~G-07 ∪ 后续各批合法扩展（登记于 LATER_*）。"""
    paths, endpoints = _actual(app)
    previous = BATCH2_ENDPOINTS | BATCH3_ENDPOINTS
    assert endpoints - previous == BATCH4_NEW_ENDPOINTS | LATER_ENDPOINTS
    assert paths - (BATCH2_PATHS | BATCH3_PATHS) == BATCH4_NEW_PATHS | LATER_PATHS


def test_t_no_out_of_scope_modules_registered(app):
    """T：**V1.0 明确不做**的模块仍不得注册（S/E/D/A-07 已由后续批次正式纳入）。"""
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


def test_t_y01_health_remains_unauthenticated_and_public(client):
    """T：Y-01 健康检查保持免认证（不在本批改动范围）。"""
    assert client.get("/api/v1/health").status_code == 200


# ════════════════════════════════════════════════════════════════════
# 医疗红线 —— 源码 / 注释
# ════════════════════════════════════════════════════════════════════
def test_redline_source_scan():
    """红线-1：本批生产代码不含医学内容（声明句豁免）。"""
    assert len(BATCH4_FILES) == 6
    hits = []
    scanned = 0
    for rel in BATCH4_FILES:
        path = BACKEND / rel
        assert path.is_file(), f"待扫描文件不存在：{rel}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            scanned += 1
            if _is_exempt(line):
                continue
            for term in BANNED_TERMS:
                if term in line:
                    hits.append(f"{rel}:{lineno} 命中「{term}」：{line.strip()[:120]}")
    assert scanned > 500, f"扫描行数异常（{scanned}）"
    assert not hits, "判定命中：\n" + "\n".join(hits)


def test_redline_no_medical_interpretation_fields():
    """红线-2：本批响应结构**不含**任何医学解释字段名。"""
    banned_keys = ("diagnosis", "advice", "suggestion", "risk_level", "risk",
                   "health_score", "conclusion", "recommendation", "abnormal")
    hits = []
    for rel in BATCH4_FILES:
        path = BACKEND / rel
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _is_exempt(line):
                continue
            for key in banned_keys:
                if f'"{key}"' in line or f"'{key}'" in line:
                    hits.append(f"{rel}:{lineno} 「{key}」")
    assert not hits, hits


def test_redline_runtime_messages_are_neutral(client, user):
    """红线-3：G 接口的运行期文案中性（含错误 / 软提示 / 完成度文案）。"""
    from tests.batch4.conftest import create_goal

    texts = []
    samples = [
        create_goal(client, user["header"], goal_type="water", target_value=2000),
        create_goal(client, user["header"], goal_type="water", target_value=30000),   # 硬拦截
        create_goal(client, user["header"], goal_type="bp", target_value=1),          # 非法类型
        client.get("/api/v1/goals", headers=user["header"]),
        client.get("/api/v1/goals", headers=user["header"], query_string={"goal_type": "bp"}),
        client.get("/api/v1/goals/progress", headers=user["header"]),
        client.get("/api/v1/goals/99999999", headers=user["header"]),
        client.delete("/api/v1/goals/99999999", headers=user["header"]),
        client.post("/api/v1/goals/99999999/pause", headers=user["header"]),
        client.get("/api/v1/goals"),                                                 # 401
    ]
    for sample in samples:
        body = sample.get_json()
        assert body is not None, sample.status_code
        texts.append(body.get("message") or "")
        for err in body.get("errors") or []:
            texts.append(err.get("message") or "")
        data = body.get("data")
        if isinstance(data, dict):
            for item in data.get("items") or []:
                if isinstance(item, dict) and item.get("remaining_text"):
                    texts.append(item["remaining_text"])
            for warning in data.get("warnings") or []:
                texts.append(warning.get("message") or "")

    assert len(texts) >= 10
    for text in texts:
        for term in BANNED_TERMS:
            assert term not in text, f"运行期文案命中「{term}」：{text}"


def test_redline_progress_payload_has_no_interpretation(client, user):
    """红线-4：G-07 载荷**不含**医学解释字段（诊断 / 建议 / 风险 / 评分 / 达标评价词）。"""
    from tests.batch4.conftest import create_goal

    create_goal(client, user["header"], goal_type="water", target_value=2000)
    payload = client.get("/api/v1/goals/progress", headers=user["header"]).get_json()["data"]
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

    walk(payload)
    # 不返回"未设目标"之类文案
    assert "未设" not in str(payload)


def test_batch4_files_are_readable_utf8():
    """红线-5：本批文件均为 UTF-8 且非空（防止扫描被绕过）。"""
    for rel in BATCH4_FILES:
        text = (BACKEND / rel).read_text(encoding="utf-8")
        assert len(text) > 200, f"{rel} 内容异常"
