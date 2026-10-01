# -*- coding: utf-8 -*-
"""C. 契约测试（5 项）—— 统一响应壳 / request_id / 状态码 / 冻结错误码集合。

冻结依据：
- 《S1-B 第二批 API 接口设计文档》§3.4 成功结构 / §3.5 失败结构 / §3.6 错误码（18 个）/ §3.7 request_id
- 《S1-D 技术方案最终冻结》§6.x
"""
from __future__ import annotations

import re

import pytest

from app.core.errors import ERROR_HTTP_STATUS, ERROR_MESSAGE, ErrorCode
from app.core.security import generate_access_token_id, generate_refresh_token, hash_refresh_token
from tests.conftest import (
    API,
    DEFAULT_PASSWORD,
    DEFAULT_PASSWORD2,
    auth_header,
    login,
    register,
    unique_username,
)

#: S1-B §3.6 冻结的 18 个错误码 ＋ **B3 追加的 1 个**（``EMAIL_TAKEN``，
#: CR-F006-001 / 授权 §Q-B3-03）⇒ 共 **19**。
#: 规则仍是「**不得改名 / 不得改语义 / 不得改 HTTP 状态**」（add-only）。
FROZEN_CODES = {
    "INVALID_PARAM",
    "UNAUTHENTICATED",
    "CREDENTIALS_INVALID",
    "TOKEN_REUSED",
    "RESOURCE_NOT_FOUND",
    "USERNAME_TAKEN",
    "GOAL_TYPE_EXISTS",
    "EXPORT_IN_PROGRESS",
    "IDEMPOTENCY_CONFLICT",
    "COUNT_MISMATCH",
    "EMAIL_TAKEN",  # B3 追加（授权 §Q-B3-03）：邮箱绑定唯一冲突（409）
    "EXPORT_EXPIRED",
    "VALIDATION_FAILED",
    "PASSWORD_INVALID",
    "ACCOUNT_LOCKED",
    "SESSION_VERIFY_ABORTED",
    "SOFT_WARNING",
    "INTERNAL_ERROR",
    "SERVICE_UNAVAILABLE",
}

REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
BASE_KEYS = ["code", "data", "message", "request_id"]


def _case_matrix(client):
    """收集一批（响应, 期望状态码）样本，覆盖成功与主要失败路径。

    注意顺序：**刷新会轮换（吊销）旧会话**，因此「登出 / 旧 Token 失效」类
    断言必须排在刷新之前，或使用另一账号的会话。
    """
    # 账号 1：登出 / 鉴权失效路径
    u1, r1 = register(client, unique_username())
    t1 = r1.get_json()["data"]["tokens"]
    h1 = auth_header(t1["access_token"])

    # 账号 2：改密校验 / 刷新与重放路径
    _u2, r2 = register(client, unique_username())
    t2 = r2.get_json()["data"]["tokens"]
    h2 = auth_header(t2["access_token"])

    return [
        (r1, 201),                                                            # 注册成功
        (client.post(f"{API}/auth/login",
                     json={"username": u1, "password": DEFAULT_PASSWORD}), 200),
        (client.post(f"{API}/auth/login",
                     json={"username": u1, "password": "wrongpw123"}), 401),
        (client.post(f"{API}/auth/register",
                     json={"username": u1, "password": DEFAULT_PASSWORD,
                           "agreement_version": "v1.0", "agreement_accepted": True}), 409),
        (client.post(f"{API}/auth/register",
                     json={"username": unique_username(), "password": "abcdefgh",
                           "agreement_version": "v1.0", "agreement_accepted": True}), 422),
        (client.post(f"{API}/auth/register", json={"username": "zz"}), 400),
        (client.get(f"{API}/users/me", headers=h1), 200),
        (client.get(f"{API}/users/me"), 401),
        (client.get(f"{API}/users/me?user_id=1", headers=h1), 400),
        (client.put(f"{API}/auth/password", headers=h2,
                    json={"old_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD2,
                          "confirm_password": "mismatch1"}), 422),
        (client.put(f"{API}/auth/password", headers=h2,
                    json={"old_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD2,
                          "confirm_password": DEFAULT_PASSWORD2, "user_id": 1}), 400),
        (client.post(f"{API}/auth/logout", headers=h1), 200),
        (client.post(f"{API}/auth/logout", headers=h1), 401),
        (client.put(f"{API}/auth/password", headers=h1,
                    json={"old_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD2,
                          "confirm_password": DEFAULT_PASSWORD2}), 401),
        (client.post(f"{API}/auth/refresh", json={"refresh_token": "bad"}), 401),
        (client.post(f"{API}/auth/refresh",
                     json={"refresh_token": t2["refresh_token"]}), 200),
        (client.post(f"{API}/auth/refresh",
                     json={"refresh_token": t2["refresh_token"]}), 401),      # TOKEN_REUSED
        (client.get(f"{API}/users/me", headers=h2), 401),                     # 重放后全失效
        (client.get(f"{API}/does-not-exist"), 404),
        (client.get(f"{API}/health"), 200),
    ]


# ════════════════════════════════════════════════════════════════════
# C-1 响应四字段完整 + C-2 request_id 格式 + C-3 与响应头一致
# ════════════════════════════════════════════════════════════════════
def test_c1_response_envelope_has_four_keys(client):
    """C-1 成功与失败响应均含 ``code`` / ``message`` / ``data`` / ``request_id``。"""
    for resp, _expected in _case_matrix(client):
        body = resp.get_json()
        assert isinstance(body, dict), resp.get_data(as_text=True)
        for key in BASE_KEYS:
            assert key in body, f"{resp.request.path} 缺字段 {key}"
        assert isinstance(body["code"], str) and body["code"]
        assert isinstance(body["message"], str) and body["message"]


def test_c2_request_id_is_32_hex(client):
    """C-2 ``request_id`` 为 32 位十六进制。"""
    for resp, _expected in _case_matrix(client):
        rid = resp.get_json()["request_id"]
        assert REQUEST_ID_RE.match(str(rid)), f"非法 request_id: {rid!r}"


def test_c3_request_id_matches_header(client):
    """C-3 ``request_id`` 与响应头 ``X-Request-Id`` 一致。"""
    for resp, _expected in _case_matrix(client):
        body = resp.get_json()
        assert resp.headers.get("X-Request-Id") == body["request_id"]
        assert REQUEST_ID_RE.match(str(resp.headers.get("X-Request-Id")))


# ════════════════════════════════════════════════════════════════════
# C-4 状态码符合设计
# ════════════════════════════════════════════════════════════════════
def test_c4_http_status_matches_contract(client):
    """C-4 HTTP 状态码与 S1-B 设计一致，且与错误码映射表相符。"""
    for resp, expected in _case_matrix(client):
        assert resp.status_code == expected, (
            f"{resp.request.method} {resp.request.path} 期望 {expected}，实际 {resp.status_code}"
        )
        code = resp.get_json()["code"]
        if code != "OK":
            assert ERROR_HTTP_STATUS[code] == resp.status_code


def test_c4b_success_status_codes(client):
    """C-4b 注册 201（创建）；登录 / 刷新 / 登出 / 当前用户 200；``SOFT_WARNING`` 若出现为 200。"""
    assert ERROR_HTTP_STATUS["SOFT_WARNING"] == 200        # 软提示用 200（非错误）
    _, resp = register(client, unique_username())
    assert resp.status_code == 201
    assert resp.get_json()["code"] == "OK"


# ════════════════════════════════════════════════════════════════════
# C-5 错误码只能使用冻结的 18 个 ＋ B3 追加的 1 个（EMAIL_TAKEN）
# ════════════════════════════════════════════════════════════════════
def test_c5_error_code_set_is_frozen(client):
    """C-5 ``ErrorCode`` / 映射表 == 冻结 18 码 ＋ B3 追加 1 码；响应中不出现表外码。"""
    declared = {
        name
        for name, value in vars(ErrorCode).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert declared == FROZEN_CODES, f"ErrorCode 与冻结集合不一致：{declared ^ FROZEN_CODES}"
    assert set(ERROR_HTTP_STATUS) == FROZEN_CODES
    assert set(ERROR_MESSAGE) == FROZEN_CODES

    observed = {resp.get_json()["code"] for resp, _ in _case_matrix(client)}
    assert observed <= (FROZEN_CODES | {"OK"}), f"出现表外错误码：{observed - FROZEN_CODES - {'OK'}}"


def test_c5b_error_message_neutral_no_medical(client):
    """C-5b 错误文案中性，不含任何医学/健康判断表述。"""
    banned = ("诊断", "疾病", "病情", "症状", "治疗", "用药", "剂量", "处方", "医嘱", "偏高", "偏低", "正常值", "参考范围", "建议就医", "风险")  # 红线禁用词
    for code, message in ERROR_MESSAGE.items():
        for word in banned:
            assert word not in message, f"{code} 文案命中禁用词 {word}: {message}"


# ════════════════════════════════════════════════════════════════════
# 附加：基础安全原语自检（不依赖外部服务）
# ════════════════════════════════════════════════════════════════════
def test_extra_token_primitives(client):
    """附加：Refresh 随机串长度与哈希口径；``jti`` 为 32 位 hex。"""
    raw = generate_refresh_token()
    assert len(raw) >= 43                       # token_urlsafe(48) ≥ 64 字符
    digest = hash_refresh_token(raw)
    assert len(digest) == 64 and digest != raw
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert len(generate_access_token_id()) == 32
    assert generate_refresh_token() != raw      # 随机性


def test_extra_password_rule_edges(client):
    """附加：密码规则边界（长度 / 字母数字组合 / 含空格 / 与用户名相同）。"""
    cases = [
        ("abc123", "密码至少 8 位"),
        ("a" * 61 + "1234", "密码最多 64 位"),
        ("abcdefgh", "密码需同时包含字母和数字"),
        ("12345678", "密码需同时包含字母和数字"),
        (f" {DEFAULT_PASSWORD} ", None),        # 首尾空格会被去除 → 合法
        ("abc 12345", "密码不得包含空格"),
    ]
    for password, expect_msg in cases:
        resp = client.post(f"{API}/auth/register", json={
            "username": unique_username(), "password": password,
            "agreement_version": "v1.0", "agreement_accepted": True})
        body = resp.get_json()
        if expect_msg is None:
            assert resp.status_code == 201, (password, body)
        else:
            assert resp.status_code == 422, (password, body)
            messages = [e["message"] for e in body["errors"]]
            assert expect_msg in messages, (password, messages)

    # 密码与用户名相同（不区分大小写）→ 拒绝
    same = unique_username()
    resp = client.post(f"{API}/auth/register", json={
        "username": same, "password": same,
        "agreement_version": "v1.0", "agreement_accepted": True})
    assert resp.status_code == 422
    messages = [e["message"] for e in resp.get_json()["errors"]]
    assert "密码不得与用户名相同" in messages

    # 仅大小写不同（用户名大写形式 + 数字）→ 视为不同，允许注册
    resp2 = client.post(f"{API}/auth/register", json={
        "username": same, "password": same.upper() + "1",
        "agreement_version": "v1.0", "agreement_accepted": True})
    assert resp2.status_code == 201, resp2.get_json()


def test_extra_username_rule_edges(client):
    """附加：用户名规则边界（长度 / 首字符 / 非法字符 / 大小写归一）。"""
    bad = [
        ("abc", "用户名长度需为 4-20 位"),
        ("a" * 21, "用户名长度需为 4-20 位"),
        ("1abcd", "用户名需以字母开头，且仅可包含字母、数字或下划线"),
        ("ab-cd", "用户名需以字母开头，且仅可包含字母、数字或下划线"),
        ("ab cd", "用户名不能包含空格"),
        ("ab@cd", "用户名需以字母开头，且仅可包含字母、数字或下划线"),
    ]
    for name, expect_msg in bad:
        resp = client.post(f"{API}/auth/register", json={
            "username": name, "password": DEFAULT_PASSWORD,
            "agreement_version": "v1.0", "agreement_accepted": True})
        assert resp.status_code == 422, (name, resp.get_json())
        messages = [e["message"] for e in resp.get_json()["errors"]]
        assert expect_msg in messages, (name, messages)

    # 大小写归一：注册 Registered，登录 registered 也应命中同一账号
    name = unique_username().upper()
    s1 = client.post(f"{API}/auth/register", json={
        "username": name, "password": DEFAULT_PASSWORD,
        "agreement_version": "v1.0", "agreement_accepted": True})
    assert s1.status_code == 201
    assert s1.get_json()["data"]["user"]["username"] == name.lower()
    assert login(client, name.lower(), DEFAULT_PASSWORD).status_code == 200
