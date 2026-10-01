# -*- coding: utf-8 -*-
"""E. 医疗红线扫描 —— 本批新增/修改的代码、注释、文案。

红线依据：《S1-D 技术方案最终冻结》§6.4 + 《S1-A 产品规则冻结书》。
- 禁止：诊断、确诊、疾病判断、病症、病情、症状、并发症
- 禁止：治疗、用药、剂量、处方、医嘱、手术、病理
- 禁止：医学结论、医学判断、参考范围结论、正常值结论、偏高/偏低结论
- 禁止：建议就医、风险判断、健康评分、风险指数

本测试做三件事：
- E-1 **源码扫描**：本批文件不得出现上述内容；声明「这些内容被禁止」的句子不计入。
- E-2 **运行期扫描**：真实接口返回的 ``message`` / ``errors[].message`` 必须中性。
- E-3 **范围守卫**：接口集合 = **当前正式基线**（2026-09-28 翻正；原为第二批时点 7 条）。
"""
from __future__ import annotations

from pathlib import Path

from tests.conftest import API, DEFAULT_PASSWORD, auth_header, register, unique_username

BACKEND = Path(__file__).resolve().parents[1]

#: 本批新增 / 修改的文件（相对 backend/）
BATCH2_FILES = (
    "app/__init__.py",
    "app/core/errors.py",
    "app/core/response.py",
    "app/core/security.py",
    "app/core/auth.py",
    "app/schemas/common.py",
    "app/schemas/auth.py",
    "app/services/auth_service.py",
    "app/api/v1/auth.py",
    "app/api/v1/users.py",
    "tests/conftest.py",
    "tests/test_auth_flow.py",
    "tests/test_auth_security.py",
    "tests/test_contract.py",
    "tests/test_medical_redline.py",
    "pytest.ini",
)

#: 红线禁用词（本行本身即声明，故包含"红线"标记）
BANNED_TERMS = ("诊断", "确诊", "疾病", "病症", "病情", "症状", "并发症", "治疗", "用药", "剂量", "处方", "医嘱", "手术", "病理", "医学结论", "医学判断", "参考范围", "正常值", "偏高", "偏低", "建议就医", "风险判断", "健康评分", "风险指数")  # noqa: E501  红线声明行

#: 豁免标记：出现任一即视为「约束声明」，不判为医学内容
EXEMPT_MARKERS = (
    "禁止", "不得", "不含", "不涉及", "非医疗", "中性", "无医学",
    "不做", "严禁", "banned", "禁用", "红线", "豁免",
)


def _is_exempt(line: str) -> bool:
    low = line.lower()
    return any(marker.lower() in low for marker in EXEMPT_MARKERS)


def test_e1_source_scan_no_medical_content():
    """E-1 本批源码 / 注释 / 文案不含医学内容。"""
    assert len(BATCH2_FILES) == 16
    scanned_lines = 0
    hits = []

    for rel in BATCH2_FILES:
        path = BACKEND / rel
        assert path.is_file(), f"待扫描文件不存在：{rel}"
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            scanned_lines += 1
            if _is_exempt(line):
                continue
            for term in BANNED_TERMS:
                if term in line:
                    hits.append(f"{rel}:{lineno} 命中「{term}」：{line.strip()[:120]}")

    assert scanned_lines > 500, f"扫描行数异常（{scanned_lines}），疑似文件缺失"
    assert not hits, "判定命中：\n" + "\n".join(hits)


def test_e2_api_messages_are_neutral(client):
    """E-2 真实接口文案中性。"""
    username, _ = register(client, unique_username())
    tokens = client.post(
        f"{API}/auth/login", json={"username": username, "password": DEFAULT_PASSWORD}
    ).get_json()["data"]["tokens"]
    header = auth_header(tokens["access_token"])

    responses = [
        client.post(f"{API}/auth/login", json={"username": username, "password": "wrongpw123"}),
        client.post(f"{API}/auth/register", json={
            "username": username, "password": DEFAULT_PASSWORD,
            "agreement_version": "v1.0", "agreement_accepted": True}),
        client.post(f"{API}/auth/register", json={
            "username": unique_username(), "password": "abcdefgh",
            "agreement_version": "v1.0", "agreement_accepted": True}),
        client.get(f"{API}/users/me", headers=header),
        client.get(f"{API}/health"),
    ]

    texts = []
    for resp in responses:
        body = resp.get_json()
        texts.append(body["message"])
        for err in body.get("errors") or []:
            texts.append(err["message"])

    assert texts, "未采集到任何文案"
    for text in texts:
        for term in BANNED_TERMS:
            assert term not in text, f"接口文案命中「{term}」：{text}"


#: ★ 翻正（2026-09-28 · Test-Baseline-Alignment Batch）：E-3 的接口集合由「第二批时点 7 条」
#:   更新为**当前正式基线 32 条唯一路径**（后续各批**合法扩展**的并集：G/S/E/D + A-07 +
#:   S4-2 头像 + B1 密码找回 + B3 邮箱绑定）。医疗红线**本体**（E-1 源码扫描 / E-2 运行期文案）
#:   **未做任何改动**。
CURRENT_PATHS = {
    "/api/v1/auth/email/bind-confirm",
    "/api/v1/auth/email/bind-request",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/password",
    "/api/v1/auth/password-reset/confirm",
    "/api/v1/auth/password-reset/request",
    "/api/v1/auth/password-reset/verify",
    "/api/v1/auth/refresh",
    "/api/v1/auth/register",
    "/api/v1/exports",
    "/api/v1/exports/<int:export_id>",
    "/api/v1/exports/<int:export_id>/download",
    "/api/v1/goals",
    "/api/v1/goals/<int:goal_id>",
    "/api/v1/goals/<int:goal_id>/pause",
    "/api/v1/goals/<int:goal_id>/resume",
    "/api/v1/goals/progress",
    "/api/v1/health",
    "/api/v1/home/overview",
    "/api/v1/me/data/clear",
    "/api/v1/me/data/summary",
    "/api/v1/profile",
    "/api/v1/profile/avatar",
    "/api/v1/records",
    "/api/v1/records/<int:record_id>",
    "/api/v1/records/batch-delete",
    "/api/v1/records/count",
    "/api/v1/records/options",
    "/api/v1/stats/summary",
    "/api/v1/stats/trend",
    "/api/v1/users/me",
}


def test_e3_scope_guard_endpoint_set(client):
    """E-3 接口集合 = **当前正式基线**（不多不少）。"""
    rules = list(client.application.url_map.iter_rules())
    actual = {str(r) for r in rules if str(r).startswith("/api/")}
    assert actual == CURRENT_PATHS, f"接口集合不符（对称差）：{actual ^ CURRENT_PATHS}"

    # ★ 翻正：A-07（S2 第八批封板）已正式纳入 → 由「不得出现」翻正为「必须已注册」
    delete_me = [
        r for r in rules
        if str(r) == "/api/v1/users/me" and "DELETE" in (r.methods or set())
    ]
    assert delete_me, "A-07 注销接口（S2 第八批封板）应已注册"
