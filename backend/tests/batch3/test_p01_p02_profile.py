# -*- coding: utf-8 -*-
"""S2 第三批 A/B —— P-01 获取档案、P-02 更新档案（含 SOFT_WARNING 与字段级警告体系）。

覆盖验收项：A（P-01 / P-02）、B（P-02 软提示）、K（当前用户隔离）、P/Q（响应契约）。
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core.errors import ERROR_MESSAGE, ErrorCode
from app.core.warnings import WarningCode
from tests.batch3.conftest import API, DEFAULT_PASSWORD, created_record, make_user, post_record, set_profile

#: P-01 ``data.profile`` 固定键（§3.13：未填写字段**保留键**并返回 null）
#: ★ 翻正（2026-09-28 · Test-Baseline-Alignment Batch）：S4-2 追加 1 键
#:   ``avatar_updated_at``（**只暴露头像最后更新时间**；无 ``avatar_key`` / 无路径）→ 11 → 12
PROFILE_KEYS = {
    "nickname", "gender", "birth_date", "age", "height_cm", "initial_weight_kg",
    "blood_type", "medical_history", "allergy_history", "medication_notes", "updated_at",
    "avatar_updated_at",
}


def test_p01_uninitialized_returns_all_null_not_404(client, user):
    """A-1：未初始化档案 → 全 null 对象（**不是 404**）。"""
    resp = client.get(f"{API}/profile", headers=user["header"])
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK"
    profile = body["data"]["profile"]
    assert set(profile.keys()) == PROFILE_KEYS
    assert all(profile[k] is None for k in PROFILE_KEYS)
    assert body["data"]["derived"]["bmi"] is None
    assert body["data"]["derived"]["bmi_source"] is None


def test_p01_target_weight_is_guidance_only(client, user):
    """A-2：``target_weight`` **只给取数指引**（D-1：唯一源 = health_goal）。"""
    resp = client.get(f"{API}/profile", headers=user["header"])
    guide = resp.get_json()["data"]["target_weight"]
    assert guide["from"] == "health_goal"
    assert guide["available_at"] == "/api/v1/goals?goal_type=weight"
    assert "weight" not in guide or guide.get("weight") is None
    assert "value" not in guide and "target_weight_kg" not in guide


def test_p01_age_computed_by_server(client, user):
    """A-3：``age`` 由服务端按 ``birth_date`` 计算（派生值不落库）。"""
    set_profile(client, user["header"], birth_date="1995-03-18")
    resp = client.get(f"{API}/profile", headers=user["header"])
    expected = date.today().year - 1995 - ((date.today().month, date.today().day) < (3, 18))
    assert resp.get_json()["data"]["profile"]["age"] == expected


def test_p01_bmi_requires_weight_record_and_height(client, ready_user):
    """A-4：BMI 需要「最新有效体重记录 + 身高」，缺失任一 → null。"""
    resp = client.get(f"{API}/profile", headers=ready_user["header"])
    assert resp.get_json()["data"]["derived"]["bmi"] is None      # 尚无体重记录

    post_record(client, ready_user["header"],
                {"metric_type": "weight", "value_1": 72.5,
                 "recorded_at": "2026-09-13 07:30:00"})
    resp = client.get(f"{API}/profile", headers=ready_user["header"])
    derived = resp.get_json()["data"]["derived"]
    assert derived["bmi"] == 23.7, derived
    assert derived["bmi_source"]["weight_kg"] == 72.5
    assert derived["bmi_source"]["height_cm"] == 175.0
    assert derived["bmi_source"]["weight_recorded_at"] == "2026-09-13 07:30:00"


def test_p01_bmi_uses_latest_weight_record(client, ready_user):
    """A-5：BMI 取**最近一条**体重记录。"""
    post_record(client, ready_user["header"],
                {"metric_type": "weight", "value_1": 80.0, "recorded_at": "2026-09-10 07:00:00"})
    post_record(client, ready_user["header"],
                {"metric_type": "weight", "value_1": 70.0, "recorded_at": "2026-09-13 07:00:00"})
    derived = client.get(f"{API}/profile", headers=ready_user["header"]).get_json()["data"]["derived"]
    assert derived["bmi"] == round(70.0 / (1.75 ** 2), 1), derived


def test_p02_whole_replacement_and_upsert(client, user):
    """A-6：PUT 为整体替换 / UPSERT（省略即置空）。"""
    set_profile(client, user["header"], nickname="甲", gender=1, height_cm=170.0)
    resp = set_profile(client, user["header"], nickname="乙")
    assert resp.status_code == 200 and resp.get_json()["code"] == "OK"
    profile = resp.get_json()["data"]["profile"]
    assert profile["nickname"] == "乙"
    assert profile["gender"] is None and profile["height_cm"] is None   # 省略即置空
    assert resp.get_json()["data"]["warnings"] == []                    # 数组永不返回 null


def test_p02_rejects_target_weight(client, user):
    """A-7：**D-1 保护** —— 本接口不接受 ``target_weight``（防双数据源）。"""
    resp = client.put(f"{API}/profile", headers=user["header"],
                      json={"nickname": "甲", "target_weight": 70})
    assert resp.status_code == 422, resp.get_json()
    assert resp.get_json()["code"] == "VALIDATION_FAILED"
    fields = {e["field"] for e in resp.get_json().get("errors") or []}
    assert "target_weight" in fields


def test_p02_rejects_client_user_id(client, user):
    """A-8：请求体携带 ``user_id`` → 400（user_id 只能由服务端从 Token 解析）。"""
    resp = client.put(f"{API}/profile", headers=user["header"],
                      json={"nickname": "甲", "user_id": 999})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "INVALID_PARAM"


def test_p02_enum_and_date_validation(client, user):
    """A-9：枚举非法 / 未来日期 → 422。"""
    future = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert set_profile(client, user["header"], gender=9).status_code == 422
    assert set_profile(client, user["header"], blood_type="X").status_code == 422
    assert set_profile(client, user["header"], birth_date=future).status_code == 422
    assert set_profile(client, user["header"], birth_date="1899-12-31").status_code == 422
    assert set_profile(client, user["header"], birth_date="1995/03/18").status_code == 422


def test_p02_text_length_and_precision(client, user):
    """A-10：文本超长 / 小数位越界 → 422。"""
    assert set_profile(client, user["header"], nickname="x" * 21).status_code == 422
    assert set_profile(client, user["header"], medical_history="x" * 2001).status_code == 422
    assert set_profile(client, user["header"], height_cm=175.25).status_code == 422
    assert set_profile(client, user["header"], initial_weight_kg=72.55).status_code == 422
    assert set_profile(client, user["header"], nickname="正常").status_code == 200


def test_p02_soft_warning_blocks_write_until_acknowledged(client, user):
    """B：软提示 —— HTTP 200 + SOFT_WARNING，**本次不写入**；确认后写入原值。"""
    resp = set_profile(client, user["header"], height_cm=5000.0)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == ErrorCode.SOFT_WARNING
    assert body["message"] == ERROR_MESSAGE[ErrorCode.SOFT_WARNING]
    assert body["data"]["requires_confirm"] is True
    warning = body["data"]["warnings"][0]
    assert warning["field"] == "height_cm"
    assert warning["code"] == WarningCode.OUT_OF_COMMON_RANGE

    # 未写入
    assert client.get(f"{API}/profile", headers=user["header"]).get_json()["data"]["profile"]["height_cm"] is None

    # 确认后写入原值（原样重发 + acknowledge_warnings）
    ok = set_profile(client, user["header"], height_cm=5000.0, acknowledge_warnings=True)
    assert ok.status_code == 200 and ok.get_json()["code"] == "OK", ok.get_json()
    assert ok.get_json()["data"]["profile"]["height_cm"] == 5000.0
    assert ok.get_json()["data"]["warnings"][0]["code"] == WarningCode.OUT_OF_COMMON_RANGE


def test_p02_soft_warning_initial_weight(client, user):
    """B：初始体重超区间同样为软提示（区间 20–300，来源 S1-B §六 P-02）。"""
    resp = set_profile(client, user["header"], initial_weight_kg=5.0)
    assert resp.status_code == 200 and resp.get_json()["code"] == "SOFT_WARNING"
    assert resp.get_json()["data"]["warnings"][0]["field"] == "initial_weight_kg"


def test_p02_in_range_writes_directly(client, user):
    """B：区间内直接写入（不产生 warnings）。"""
    resp = set_profile(client, user["header"], height_cm=175.0, initial_weight_kg=72.5)
    assert resp.status_code == 200 and resp.get_json()["data"]["warnings"] == []


def test_p02_does_not_extend_field_error_code(client, user):
    """B：``OUT_OF_COMMON_RANGE`` **不得**出现在第二批封板的 ``errors[].code`` 体系内。"""
    from app.core.errors import FieldErrorCode

    frozen = {
        FieldErrorCode.REQUIRED, FieldErrorCode.INVALID_TYPE, FieldErrorCode.INVALID_FORMAT,
        FieldErrorCode.WEAK_PASSWORD, FieldErrorCode.MISMATCH,
        FieldErrorCode.SAME_AS_OLD, FieldErrorCode.NOT_ACCEPTED,
    }
    assert len(frozen) == 7
    assert WarningCode.OUT_OF_COMMON_RANGE not in frozen
    resp = set_profile(client, user["header"], height_cm=5000.0)
    assert WarningCode.OUT_OF_COMMON_RANGE in {w["code"] for w in resp.get_json()["data"]["warnings"]}
    # 软提示响应不带 errors[]
    assert "errors" not in resp.get_json()


def test_p01_isolation_between_users(client, user, peer):
    """K/L：档案按 Token 隔离，第二个账号读到的是自己的空档案。"""
    set_profile(client, user["header"], nickname="甲", height_cm=175.0)
    other = client.get(f"{API}/profile", headers=peer["header"]).get_json()["data"]["profile"]
    assert other["nickname"] is None and other["height_cm"] is None
    assert client.get(f"{API}/profile", headers=user["header"]).get_json()["data"]["profile"]["nickname"] == "甲"


def test_p01_p02_require_auth(client):
    """L：P-01 / P-02 必须认证。"""
    assert client.get(f"{API}/profile").status_code == 401
    assert client.put(f"{API}/profile", json={"nickname": "x"}).status_code == 401
    assert client.get(f"{API}/profile", headers={"Authorization": "Bearer bad"}).status_code == 401


def test_profile_query_user_id_rejected(client, user):
    """A-8：query 携带 ``user_id`` 同样 → 400。"""
    resp = client.get(f"{API}/profile?user_id=1", headers=user["header"])
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"


def test_profile_response_contract(client, user):
    """P/Q：统一响应契约四键 + ``X-Request-Id`` 与 ``request_id`` 一致。"""
    resp = client.get(f"{API}/profile", headers=user["header"])
    body = resp.get_json()
    assert sorted(body.keys()) == ["code", "data", "message", "request_id"]
    assert len(body["request_id"]) == 32
    assert resp.headers["X-Request-Id"] == body["request_id"]
