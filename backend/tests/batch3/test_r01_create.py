# -*- coding: utf-8 -*-
"""S2 第三批 C/O —— R-01 新增健康记录（含 8 类指标矩阵、硬拦截/软提示、幂等键）。

覆盖验收项：C（R-01 新增）、O（Idempotency-Key）、P/Q（响应契约）、M（软删可见性不含本项）。
"""
from __future__ import annotations

from app.core.errors import ErrorCode
from app.core.warnings import WarningCode
from tests.batch3.conftest import API, created_record, post_record

#: 8 类指标的合法最小请求体（§七 R-01 示例逐条对齐）
VALID_PAYLOADS = {
    "weight": {"metric_type": "weight", "value_1": 72.5, "recorded_at": "2026-09-13 07:30:00"},
    "bp": {"metric_type": "bp", "value_1": 128, "value_2": 82, "value_3": 76,
           "attr_1": "morning", "recorded_at": "2026-09-13 07:35:00"},
    "heart": {"metric_type": "heart", "value_1": 72, "attr_1": "resting",
              "recorded_at": "2026-09-13 07:40:00"},
    "glucose": {"metric_type": "glucose", "value_1": 5.6, "attr_1": "fasting",
                "recorded_at": "2026-09-13 07:45:00"},
    "sleep": {"metric_type": "sleep", "time_start": "2026-09-12 23:30:00",
              "recorded_at": "2026-09-13 07:00:00", "value_1": 4},
    "water": {"metric_type": "water", "value_1": 250, "recorded_at": "2026-09-13 09:00:00"},
    "sport": {"metric_type": "sport", "value_1": 45, "value_2": 380, "attr_1": "running",
              "attr_2": "mid", "recorded_at": "2026-09-13 18:30:00"},
    "mood": {"metric_type": "mood", "value_1": 4, "tags": ["relaxed", "focused"],
             "recorded_at": "2026-09-13 21:00:00"},
}

UNIT_OF = {"weight": "kg", "bp": "mmHg", "heart": "bpm", "glucose": "mmol/L",
           "sleep": "score", "water": "ml", "sport": "min", "mood": "score"}


def test_r01_all_eight_metrics_accepted(client, user):
    """C：8 类指标全部可新增 201，且单位由服务端填充。"""
    for metric, payload in VALID_PAYLOADS.items():
        resp = post_record(client, user["header"], payload)
        assert resp.status_code == 201, (metric, resp.get_json())
        record = resp.get_json()["data"]["record"]
        assert record["metric_type"] == metric
        assert record["unit"] == UNIT_OF[metric]
        assert resp.get_json()["data"]["warnings"] == []


def test_r01_response_contract_and_request_id(client, user):
    """P/Q：201 + 四键 + 32 位 request_id + 响应头一致。"""
    resp = post_record(client, user["header"], VALID_PAYLOADS["water"])
    body = resp.get_json()
    assert resp.status_code == 201
    assert sorted(body.keys()) == ["code", "data", "message", "request_id"]
    assert len(body["request_id"]) == 32
    assert resp.headers["X-Request-Id"] == body["request_id"]
    assert set(body["data"].keys()) == {"record", "derived", "warnings"}


def test_r01_required_matrix(client, user):
    """C：必填矩阵（缺失必填 → 422）。"""
    cases = [
        {"metric_type": "bp", "value_1": 128, "recorded_at": "2026-09-13 07:35:00"},          # 缺 value_2
        {"metric_type": "glucose", "value_1": 5.6, "recorded_at": "2026-09-13 07:45:00"},    # 缺 attr_1
        {"metric_type": "sleep", "recorded_at": "2026-09-13 07:00:00"},                      # 缺 time_start
        {"metric_type": "sleep", "time_start": "2026-09-12 23:30:00"},                       # 缺 recorded_at
        {"metric_type": "sport", "value_1": 45, "recorded_at": "2026-09-13 18:30:00"},       # 缺 attr_1
        {"metric_type": "mood", "recorded_at": "2026-09-13 21:00:00"},                       # 缺 value_1
    ]
    for payload in cases:
        resp = post_record(client, user["header"], payload)
        assert resp.status_code == 422, (payload, resp.get_json())


def test_r01_forbidden_fields_per_metric(client, user):
    """C：禁止字段矩阵（携带 → 422）。"""
    cases = [
        {"metric_type": "weight", "value_1": 72.5, "value_2": 1, "recorded_at": "2026-09-13 07:30:00"},
        {"metric_type": "weight", "value_1": 72.5, "attr_1": "morning", "recorded_at": "2026-09-13 07:30:00"},
        {"metric_type": "heart", "value_1": 72, "tags": ["tired"], "recorded_at": "2026-09-13 07:40:00"},
        {"metric_type": "water", "value_1": 250, "time_start": "2026-09-13 08:00:00",
         "recorded_at": "2026-09-13 09:00:00"},
        {"metric_type": "mood", "value_1": 4, "attr_1": "resting", "recorded_at": "2026-09-13 21:00:00"},
        {"metric_type": "bp", "value_1": 128, "value_2": 82, "attr_2": "mid",
         "recorded_at": "2026-09-13 07:35:00"},
    ]
    for payload in cases:
        resp = post_record(client, user["header"], payload)
        assert resp.status_code == 422, (payload, resp.get_json())


def test_r01_metric_type_controlled_enum(client, user):
    """C：``metric_type`` 为受控枚举（非法 → 422；缺失 → 400）。"""
    resp = post_record(client, user["header"],
                       {"metric_type": "bmi", "value_1": 1, "recorded_at": "2026-09-13 07:00:00"})
    assert resp.status_code == 422, resp.get_json()
    resp = post_record(client, user["header"], {"value_1": 1, "recorded_at": "2026-09-13 07:00:00"})
    assert resp.status_code == 400, resp.get_json()


def test_r01_hard_block_out_of_possible_range(client, user):
    """C：明显不可能值 → 422 硬拦截，**不写入**（区间来源 S0 §流程 4）。"""
    cases = [
        {"metric_type": "weight", "value_1": 5000, "recorded_at": "2026-09-13 07:30:00"},
        {"metric_type": "heart", "value_1": 0, "recorded_at": "2026-09-13 07:40:00"},
        {"metric_type": "water", "value_1": 6000, "recorded_at": "2026-09-13 09:00:00"},
        {"metric_type": "sport", "value_1": 2000, "attr_1": "running", "recorded_at": "2026-09-13 18:30:00"},
        {"metric_type": "mood", "value_1": 9, "recorded_at": "2026-09-13 21:00:00"},
    ]
    for payload in cases:
        resp = post_record(client, user["header"], payload)
        assert resp.status_code == 422, (payload, resp.get_json())
    assert client.get(f"{API}/records/count", headers=user["header"]).get_json()["data"]["count"] == 0


def test_r01_hard_block_field_contradiction(client, user):
    """C：字段间逻辑矛盾 → 422（舒张压 ≥ 收缩压；入睡时间 ≥ 起床时间）。"""
    resp = post_record(client, user["header"],
                       {"metric_type": "bp", "value_1": 80, "value_2": 120,
                        "recorded_at": "2026-09-13 07:35:00"})
    assert resp.status_code == 422 and resp.get_json()["code"] == "VALIDATION_FAILED"

    resp = post_record(client, user["header"],
                       {"metric_type": "sleep", "time_start": "2026-09-13 08:00:00",
                        "recorded_at": "2026-09-13 07:00:00"})
    assert resp.status_code == 422, resp.get_json()


def test_r01_future_recorded_at_blocked(client, user):
    """C：``recorded_at`` 为未来 → 422。"""
    resp = post_record(client, user["header"],
                       {"metric_type": "weight", "value_1": 72.5,
                        "recorded_at": "2099-01-01 00:00:00"})
    assert resp.status_code == 422, resp.get_json()


def test_r01_soft_warning_blocks_write_then_ack_writes(client, user):
    """C+B：疑似录入错误 → 200 ``SOFT_WARNING``（不写入）；确认后写入原值。"""
    resp = post_record(client, user["header"],
                       {"metric_type": "weight", "value_1": 320, "recorded_at": "2026-09-13 07:30:00"})
    body = resp.get_json()
    assert resp.status_code == 200 and body["code"] == ErrorCode.SOFT_WARNING
    assert body["data"]["requires_confirm"] is True
    assert body["data"]["warnings"][0]["code"] == WarningCode.OUT_OF_COMMON_RANGE
    assert client.get(f"{API}/records/count", headers=user["header"]).get_json()["data"]["count"] == 0

    ack = post_record(client, user["header"],
                      {"metric_type": "weight", "value_1": 320, "acknowledge_warnings": True,
                       "recorded_at": "2026-09-13 07:30:00"})
    assert ack.status_code == 201, ack.get_json()
    assert ack.get_json()["data"]["record"]["value_1"] == 320
    assert ack.get_json()["data"]["warnings"][0]["code"] == WarningCode.OUT_OF_COMMON_RANGE


def test_r01_sleep_duration_soft_warning(client, user):
    """C：睡眠时长超出常见区间（1–16h）→ 软提示。"""
    resp = post_record(client, user["header"],
                       {"metric_type": "sleep", "time_start": "2026-09-12 12:00:00",
                        "recorded_at": "2026-09-13 07:00:00"})     # 19h
    assert resp.status_code == 200 and resp.get_json()["code"] == ErrorCode.SOFT_WARNING
    resp = post_record(client, user["header"],
                       {"metric_type": "sleep", "time_start": "2026-09-11 07:00:00",
                        "recorded_at": "2026-09-13 07:00:00"})     # 48h → 硬拦截
    assert resp.status_code == 422, resp.get_json()


def test_r01_derived_values_not_persisted(client, ready_user):
    """C：派生值**不落库**，按指标实时返回（weight→bmi / sleep→时长 / water→当日累计）。"""
    resp = post_record(client, ready_user["header"],
                       {"metric_type": "weight", "value_1": 70.0, "recorded_at": "2026-09-13 07:30:00"})
    assert resp.get_json()["data"]["derived"]["bmi"] == 22.9

    resp = post_record(client, ready_user["header"],
                       {"metric_type": "sleep", "time_start": "2026-09-12 23:30:00",
                        "recorded_at": "2026-09-13 07:00:00"})
    derived = resp.get_json()["data"]["derived"]
    assert derived["sleep_duration_minutes"] == 450
    assert derived["sleep_duration_hours"] == 7.5

    post_record(client, ready_user["header"],
                {"metric_type": "water", "value_1": 250, "recorded_at": "2026-09-13 09:00:00"})
    resp = post_record(client, ready_user["header"],
                       {"metric_type": "water", "value_1": 500, "recorded_at": "2026-09-13 10:00:00"})
    assert resp.get_json()["data"]["derived"]["today_total_ml"] == 750


def test_r01_tags_only_for_mood(client, user):
    """C：标签仅 mood 允许（取值受控、去重保序；``mood_tags`` 字典共 6 值）。"""
    resp = post_record(client, user["header"],
                       {"metric_type": "mood", "value_1": 3, "tags": ["relaxed", "relaxed", "tired"],
                        "recorded_at": "2026-09-13 21:00:00"})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["data"]["record"]["tags"] == ["relaxed", "tired"]

    # 非法标签取值 → 422
    assert post_record(client, user["header"],
                       {"metric_type": "mood", "value_1": 3, "tags": ["unknown_tag"],
                        "recorded_at": "2026-09-13 21:00:00"}).status_code == 422
    # 字典内 6 个取值全量提交且含重复 → 去重后恰 6 个，合法
    resp = post_record(client, user["header"],
                       {"metric_type": "mood", "value_1": 3,
                        "tags": ["tired", "anxious", "relaxed", "focused", "low",
                                 "energetic", "tired"],
                        "recorded_at": "2026-09-13 21:00:00"})
    assert resp.status_code == 201, resp.get_json()
    assert set(resp.get_json()["data"]["record"]["tags"]) == {
        "tired", "anxious", "relaxed", "focused", "low", "energetic"}
    # 标签仅 mood 允许
    assert post_record(client, user["header"],
                       {"metric_type": "weight", "value_1": 70, "tags": ["tired"],
                        "recorded_at": "2026-09-13 07:30:00"}).status_code == 422


def test_r01_user_id_injection_blocked(client, user):
    """C：请求体携带 ``user_id`` → 400（服务端 user_id 只能来自 Token）。"""
    payload = dict(VALID_PAYLOADS["weight"])
    payload["user_id"] = 1
    resp = post_record(client, user["header"], payload)
    assert resp.status_code == 400 and resp.get_json()["code"] == "INVALID_PARAM"
    assert client.get(f"{API}/records/count", headers=user["header"]).get_json()["data"]["count"] == 0


def test_r01_unit_mismatch_blocked(client, user):
    """C：单位由服务端填充；客户端传入不一致 → 422。"""
    payload = dict(VALID_PAYLOADS["weight"])
    payload["unit"] = "lb"
    assert post_record(client, user["header"], payload).status_code == 422
    payload["unit"] = "kg"
    assert post_record(client, user["header"], payload).status_code == 201


def test_r01_attribute_enum_controlled(client, user):
    """C：``attr_1`` / ``attr_2`` 为受控枚举。"""
    bad = dict(VALID_PAYLOADS["heart"])
    bad["attr_1"] = "unknown_state"
    assert post_record(client, user["header"], bad).status_code == 422

    bad2 = dict(VALID_PAYLOADS["sport"])
    bad2["attr_2"] = "extreme"
    assert post_record(client, user["header"], bad2).status_code == 422


def test_r01_precision_and_type(client, user):
    """C：精度越界 / 非数字 → 422 / 400。"""
    bad = dict(VALID_PAYLOADS["glucose"])
    bad["value_1"] = 5.67                      # 血糖仅 1 位小数
    assert post_record(client, user["header"], bad).status_code == 422

    bad2 = dict(VALID_PAYLOADS["bp"])
    bad2["value_1"] = 128.5                    # 收缩压仅整数
    assert post_record(client, user["header"], bad2).status_code == 422

    bad3 = dict(VALID_PAYLOADS["weight"])
    bad3["value_1"] = "七二点五"
    assert post_record(client, user["header"], bad3).status_code in (400, 422)


def test_r01_requires_auth(client):
    """L：R-01 必须认证。"""
    assert client.post(f"{API}/records", json=VALID_PAYLOADS["weight"]).status_code == 401


# ════════════════════════════════════════════════════════════════════
# O —— Idempotency-Key
# ════════════════════════════════════════════════════════════════════
def test_o_same_key_same_body_returns_first_result(client, user):
    """O：同 key + 同请求体 → 返回首次结果（网络重试不产生重复记录）。"""
    payload = VALID_PAYLOADS["water"]
    first = post_record(client, user["header"], payload, idem="b3-idem-key-0001")
    second = post_record(client, user["header"], payload, idem="b3-idem-key-0001")
    assert first.status_code == 201 and second.status_code == 201
    assert created_record(first)["id"] == created_record(second)["id"]
    assert client.get(f"{API}/records/count", headers=user["header"]).get_json()["data"]["count"] == 1
    # request_id 必须按本次请求重新生成（§3.7）
    assert first.get_json()["request_id"] != second.get_json()["request_id"]


def test_o_same_key_different_body_conflicts(client, user):
    """O：同 key + 不同请求体 → 409 ``IDEMPOTENCY_CONFLICT``。"""
    post_record(client, user["header"], VALID_PAYLOADS["water"], idem="b3-idem-key-0002")
    other = dict(VALID_PAYLOADS["water"])
    other["value_1"] = 500
    resp = post_record(client, user["header"], other, idem="b3-idem-key-0002")
    assert resp.status_code == 409, resp.get_json()
    assert resp.get_json()["code"] == ErrorCode.IDEMPOTENCY_CONFLICT
    assert client.get(f"{API}/records/count", headers=user["header"]).get_json()["data"]["count"] == 1


def test_o_different_key_creates_new_record(client, user):
    """O：不同 key → 正常新建。"""
    a = post_record(client, user["header"], VALID_PAYLOADS["water"], idem="b3-idem-key-0003")
    b = post_record(client, user["header"], VALID_PAYLOADS["water"], idem="b3-idem-key-0004")
    assert created_record(a)["id"] != created_record(b)["id"]
    assert client.get(f"{API}/records/count", headers=user["header"]).get_json()["data"]["count"] == 2


def test_o_without_key_always_creates(client, user):
    """O：不携带 key → 每次新建（幂等键为**可选**，F-083 第一道防线在客户端）。"""
    a = post_record(client, user["header"], VALID_PAYLOADS["water"])
    b = post_record(client, user["header"], VALID_PAYLOADS["water"])
    assert created_record(a)["id"] != created_record(b)["id"]


def test_o_idempotency_is_scoped_per_user(client, user, peer):
    """O：幂等窗口按用户隔离（同一 key 在不同用户下互不影响）。"""
    a = post_record(client, user["header"], VALID_PAYLOADS["water"], idem="b3-idem-shared")
    b = post_record(client, peer["header"], VALID_PAYLOADS["water"], idem="b3-idem-shared")
    assert a.status_code == 201 and b.status_code == 201
    assert created_record(a)["id"] != created_record(b)["id"]
