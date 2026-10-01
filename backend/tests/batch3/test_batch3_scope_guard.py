# -*- coding: utf-8 -*-
"""S2 第三批 T（范围守卫）+ 医疗红线扫描。

覆盖验收项：
- T：接口集合恰为 Y-01 + A-01~A-06 + P-01/P-02 + R-01~R-08（**共 17 条**）；
  **不含** G / S / E / D / A-07 / P1 / P2 及任何超出 S0 冻结编号的功能接口
- 红线：本批源码、注释、文案、接口运行期文案不含医学内容

> ★ **翻正（2026-09-28 · Test-Baseline-Alignment Batch）**：原名 ``EXPECTED_ENDPOINTS``
> 为 **S2 第三批时点快照（17 条）**；后续各批（b4~b8 / S4-2 / B1 / B3）的**合法扩展**
> 使其必然 FAIL —— 属**历史时点判据**。本批按授权把「当时快照」翻正为**当前正式基线**
> （:data:`CURRENT_ENDPOINTS` = 42 条 / 32 路径），并逐批登记 :data:`LATER_ENDPOINTS`；
> 原 17 条常量与 ``test_t_expected_endpoint_count_is_17`` **原样保留**（历史证据）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.batch3.conftest import API, created_record, post_record

BACKEND = Path(__file__).resolve().parents[2]

#: 本批新增 / 修改的生产代码（相对 backend/）
BATCH3_FILES = (
    "app/__init__.py",
    "app/core/warnings.py",
    "app/core/idempotency.py",
    "app/core/paging.py",
    "app/schemas/base.py",
    "app/schemas/profile.py",
    "app/schemas/record.py",
    "app/services/metric_rules.py",
    "app/services/profile_service.py",
    "app/services/record_service.py",
    "app/api/v1/profile.py",
    "app/api/v1/records.py",
)

#: 红线禁用词（与第二批一致，**不得放宽**）—— 本行即禁用词清单，属约束声明行
BANNED_TERMS = ("诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药", "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围", "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数")  # noqa: E501  红线声明行

#: 豁免标记：出现任一即视为「约束声明」，不判为医学内容
EXEMPT_MARKERS = (
    "禁止", "不得", "不含", "不涉及", "非医疗", "非医学", "中性", "无医学",
    "不做", "严禁", "banned", "禁用", "红线", "豁免",
)

#: 当前阶段允许的 API 集合（S2 第三批完成时点）
EXPECTED_ENDPOINTS = {
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

#: 本批之后各批的**合法扩展**（逐批登记；来源：各批封板报告 / 本批审计表）
#:   b4 +7（goals）｜b5 +3（stats/home）｜b6 +4（exports）｜b7 +2（me/data）
#:   b8 +1（A-07 DELETE users/me）｜S4-2 +3（profile/avatar）｜B1 +3（password-reset）｜B3 +2（email/bind）
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
    ("GET", "/api/v1/goals"),
    ("POST", "/api/v1/goals"),
    ("DELETE", "/api/v1/goals/<int:goal_id>"),
    ("PATCH", "/api/v1/goals/<int:goal_id>"),
    ("POST", "/api/v1/goals/<int:goal_id>/pause"),
    ("POST", "/api/v1/goals/<int:goal_id>/resume"),
    ("GET", "/api/v1/goals/progress"),
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
    "/api/v1/goals",
    "/api/v1/goals/<int:goal_id>",
    "/api/v1/goals/<int:goal_id>/pause",
    "/api/v1/goals/<int:goal_id>/resume",
    "/api/v1/goals/progress",
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


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(marker.lower() in low for marker in EXEMPT_MARKERS)


# ════════════════════════════════════════════════════════════════════
# T —— 范围守卫
# ════════════════════════════════════════════════════════════════════
def test_t_expected_endpoint_count_is_17():
    """T：契约自检 —— 期望集合恰 17 条（Y-01 + A×6 + P×2 + R×8）。"""
    assert len(EXPECTED_ENDPOINTS) == 17


def test_t_endpoint_set_matches_current_phase(app):
    """T：接口集合 = **当前正式基线**（不多不少）。"""
    actual = set()
    for rule in app.url_map.iter_rules():
        path = str(rule)
        if not path.startswith("/api/"):
            continue
        for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            actual.add((method, path))
    assert actual == CURRENT_ENDPOINTS, f"接口集合差异：{actual ^ CURRENT_ENDPOINTS}"


def test_t_no_out_of_scope_modules_registered(app):
    """T：**V1.0 明确不做**的模块仍不得注册（G/S/E/D/A-07 已由后续批次正式纳入）。"""
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
    resp = client.get(f"{API}/health")
    assert resp.status_code == 200


# ════════════════════════════════════════════════════════════════════
# 医疗红线 —— 源码 / 注释 / 文案
# ════════════════════════════════════════════════════════════════════
def test_redline_source_scan():
    """红线-1：本批生产代码不含医学内容（声明句豁免）。"""
    assert len(BATCH3_FILES) == 12
    hits = []
    scanned = 0
    for rel in BATCH3_FILES:
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


def test_redline_runtime_messages_are_neutral(client, user):
    """红线-2：P / R 接口的运行期文案中性（含错误与软提示）。"""
    texts = []

    # 成功
    record = created_record(post_record(client, user["header"],
                                        {"metric_type": "weight", "value_1": 70.0,
                                         "recorded_at": "2026-09-13 07:30:00"}))
    # 400 / 401 / 404 / 409 / 422 / 软提示
    samples = [
        client.get(f"{API}/records", headers=user["header"], query_string={"limit": "30"}),
        client.get(f"{API}/records"),
        client.get(f"{API}/records/99999999", headers=user["header"]),
        client.patch(f"{API}/records/{record['id']}", headers=user["header"],
                     json={"metric_type": "bp"}),
        post_record(client, user["header"],
                    {"metric_type": "weight", "value_1": 320,
                     "recorded_at": "2026-09-13 08:00:00"}),
        client.post(f"{API}/records/batch-delete", headers=user["header"],
                    json={"metric_type": "weight", "password": "wrong-password",
                          "expected_count": 99}),
        client.put(f"{API}/profile", headers=user["header"], json={}),
        client.get(f"{API}/profile", headers=user["header"]),
        client.get(f"{API}/records/options", headers=user["header"]),
    ]
    for resp in samples:
        body = resp.get_json()
        assert body is not None, resp.status_code
        texts.append(body.get("message") or "")
        for err in body.get("errors") or []:
            texts.append(err.get("message") or "")
        data = body.get("data")
        if isinstance(data, dict):
            for warning in data.get("warnings") or []:
                texts.append(warning.get("message") or "")

    assert len(texts) >= 9
    for text in texts:
        for term in BANNED_TERMS:
            assert term not in text, f"运行期文案命中「{term}」：{text}"


def test_redline_no_medical_interpretation_fields(client, user):
    """红线-3：响应**不含**任何医学解释字段（诊断 / 建议 / 风险 / 评分）。"""
    record = created_record(post_record(client, user["header"],
                                        {"metric_type": "weight", "value_1": 70.0,
                                         "recorded_at": "2026-09-13 07:30:00"}))
    payloads = [
        client.get(f"{API}/profile", headers=user["header"]).get_json()["data"],
        client.get(f"{API}/records/{record['id']}", headers=user["header"]).get_json()["data"],
        client.get(f"{API}/records/options", headers=user["header"]).get_json()["data"],
    ]
    banned_keys = ("diagnosis", "advice", "suggestion", "risk", "risk_level", "score_health",
                   "health_score", "conclusion", "recommendation")

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


@pytest.mark.parametrize("rel", BATCH3_FILES)
def test_redline_files_are_readable_utf8(rel):
    """红线-4：本批文件均为 UTF-8 且非空（防止扫描被绕过）。"""
    path = BACKEND / rel
    text = path.read_text(encoding="utf-8")
    assert len(text) > 200, f"{rel} 内容异常"
