# -*- coding: utf-8 -*-
"""S2 第三批 N（R-08 录入选项）。

覆盖验收项：N（静态枚举字典）、契约（P/Q）、无副作用。
"""
from __future__ import annotations

from app.services import metric_rules
from tests.batch3.conftest import API

EXPECTED_ENUMS = {
    "bp_timing": 6,
    "heart_state": 3,
    "glucose_timing": 4,
    "sport_type": 8,
    "sport_intensity": 3,
    "mood_tags": 6,
}


def _options(client, header):
    return client.get(f"{API}/records/options", headers=header)


def test_r08_static_options_payload(client, user):
    """N：返回 8 类指标 + 6 组枚举 + 快捷饮水量。"""
    resp = _options(client, user["header"])
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert sorted(body.keys()) == ["code", "data", "message", "request_id"]
    data = body["data"]

    assert set(data.keys()) == {"metric_types", "enums", "water_quick_add"}
    assert [m["value"] for m in data["metric_types"]] == list(metric_rules.METRIC_TYPES)
    assert all(m["label"] and m["unit"] for m in data["metric_types"])
    assert {k: len(v) for k, v in data["enums"].items()} == EXPECTED_ENUMS
    assert data["water_quick_add"] == [200, 250, 500]


def test_r08_metric_types_are_the_frozen_eight(client, user):
    """N：**不新增业务类型**（指标集合恰为冻结的 8 类）。"""
    data = _options(client, user["header"]).get_json()["data"]
    assert {m["value"] for m in data["metric_types"]} == {
        "weight", "bp", "heart", "glucose", "sleep", "water", "sport", "mood",
    }
    # 不存在「BMI / 派生指标 / 自定义指标」等动态项
    assert not any(m["value"] in ("bmi", "custom", "derived") for m in data["metric_types"])


def test_r08_pure_constant_no_side_effect(client, user):
    """N：纯常量输出（两次调用完全一致）且**不产生任何数据**。"""
    first = _options(client, user["header"]).get_json()["data"]
    second = _options(client, user["header"]).get_json()["data"]
    assert first == second == metric_rules.options_payload()
    assert client.get(f"{API}/records/count",
                      headers=user["header"]).get_json()["data"]["count"] == 0


def test_r08_enum_values_unique_and_non_medical(client, user):
    """N+红线：枚举取值唯一，且标签为**中性描述**（不含医学建议用语）。"""
    data = _options(client, user["header"]).get_json()["data"]
    banned = ("建议", "诊断", "治疗", "处方", "正常范围", "异常", "偏高", "偏低", "风险")
    for name, items in data["enums"].items():
        values = [it["value"] for it in items]
        assert len(values) == len(set(values)), name
        for it in items:
            label = it["label"]
            assert not any(word in label for word in banned), (name, label)


def test_r08_requires_auth(client):
    """L：R-08 必须认证。"""
    assert client.get(f"{API}/records/options").status_code == 401


def test_r08_static_path_does_not_collide_with_detail_route(client, user):
    """N：``/records/options`` 命中静态路由（不会被 ``<int:record_id>`` 吞掉）。"""
    resp = _options(client, user["header"])
    assert resp.status_code == 200
    assert "metric_types" in resp.get_json()["data"]
