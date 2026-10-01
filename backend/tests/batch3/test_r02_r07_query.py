# -*- coding: utf-8 -*-
"""S2 第三批 D/E（R-02 列表分页 + R-07 条数统计）。

覆盖验收项：
- D：R-02 keyset 分页（排序 / limit / cursor / 半开区间 / 不返回 total / 非法参数）
- E：R-07 count（软删不计入 / 条件筛选 / 跨用户隔离）
- M：软删不可见
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.errors import ErrorCode
from app.services.record_service import encode_cursor
from tests.batch3.conftest import API, post_record

BASE = datetime(2026, 8, 1, 8, 0, 0)


def _seed(client, header, count: int, metric: str = "weight", *, start: int = 0):
    """按分钟递增写入 ``count`` 条记录，返回 ``[recorded_at 字符串]``（旧 → 新）。"""
    stamps = []
    for i in range(count):
        at = BASE + timedelta(minutes=start + i)
        text = at.strftime("%Y-%m-%d %H:%M:%S")
        if metric == "weight":
            payload = {"metric_type": "weight", "value_1": 70.0 + i * 0.1, "recorded_at": text}
        else:
            payload = {"metric_type": "water", "value_1": 200, "recorded_at": text}
        resp = post_record(client, header, payload)
        assert resp.status_code == 201, resp.get_json()
        stamps.append(text)
    return stamps


def _list(client, header, **params):
    return client.get(f"{API}/records", headers=header, query_string=params)


def _count(client, header, **params):
    return client.get(f"{API}/records/count", headers=header, query_string=params)


# ════════════════════════════════════════════════════════════════════
# R-02 列表
# ════════════════════════════════════════════════════════════════════
def test_r02_response_shape_no_total(client, user):
    """D：响应固定 ``items`` / ``next_cursor`` / ``has_more``，**不返回 total**。"""
    _seed(client, user["header"], 3)
    body = _list(client, user["header"]).get_json()
    assert set(body["data"].keys()) == {"items", "next_cursor", "has_more"}
    assert "total" not in body["data"]
    assert len(body["data"]["items"]) == 3
    assert body["data"]["has_more"] is False
    assert body["data"]["next_cursor"] is None


def test_r02_order_is_recorded_at_desc_then_id_desc(client, user):
    """D：排序固定 ``recorded_at DESC, id DESC``。"""
    stamps = _seed(client, user["header"], 5)
    items = _list(client, user["header"]).get_json()["data"]["items"]
    assert [it["recorded_at"] for it in items] == list(reversed(stamps))


def test_r02_same_timestamp_falls_back_to_id_desc(client, user):
    """D：``recorded_at`` 相同时按 ``id DESC`` 稳定排序。"""
    same = "2026-08-05 10:00:00"
    for _ in range(4):
        post_record(client, user["header"],
                    {"metric_type": "water", "value_1": 200, "recorded_at": same})
    items = _list(client, user["header"]).get_json()["data"]["items"]
    ids = [it["id"] for it in items]
    assert ids == sorted(ids, reverse=True)


def test_r02_default_limit_is_20(client, user):
    """D：默认 ``limit=20``（写 25 条 → 首页恰好 20 条）。"""
    _seed(client, user["header"], 25)
    body = _list(client, user["header"]).get_json()["data"]
    assert len(body["items"]) == 20
    assert body["has_more"] is True
    assert body["next_cursor"]


def test_r02_cursor_pagination_is_continuous_and_terminates(client, user):
    """D：游标翻页不重不漏，末页 ``has_more=false``。"""
    stamps = _seed(client, user["header"], 25)

    page1 = _list(client, user["header"]).get_json()["data"]
    page2 = _list(client, user["header"], cursor=page1["next_cursor"]).get_json()["data"]
    assert len(page2["items"]) == 5
    assert page2["has_more"] is False
    assert page2["next_cursor"] is None

    got = [it["recorded_at"] for it in page1["items"] + page2["items"]]
    assert got == list(reversed(stamps))
    assert len(set(it["id"] for it in page1["items"] + page2["items"])) == 25


def test_r02_limit_50_and_100_allowed(client, user):
    """D：``limit`` 可选 20 / 50 / 100。"""
    _seed(client, user["header"], 60)
    assert len(_list(client, user["header"], limit=50).get_json()["data"]["items"]) == 50
    assert len(_list(client, user["header"], limit=100).get_json()["data"]["items"]) == 60


def test_r02_invalid_limit_rejected(client, user):
    """D：非法 ``limit`` → 400（不静默回退默认值）。"""
    for bad in ("30", "0", "-1", "101", "abc", "20.5"):
        resp = _list(client, user["header"], limit=bad)
        assert resp.status_code == 400, (bad, resp.get_json())
        assert resp.get_json()["code"] == ErrorCode.INVALID_PARAM


def test_r02_invalid_cursor_rejected_not_restarted(client, user):
    """D：非法 ``cursor`` → 400，**不得回退为从头发**。"""
    _seed(client, user["header"], 3)
    for bad in ("not-base64!!!", "e30", "eyJ0IjoiYmFkIiwiaWQiOjF9", "AAAA"):
        resp = _list(client, user["header"], cursor=bad)
        assert resp.status_code == 400, (bad, resp.get_json())
        assert resp.get_json()["code"] == ErrorCode.INVALID_PARAM


def test_r02_cursor_from_other_user_is_not_privilege_escalation(client, user, peer):
    """D：cursor 只承载"位置"，不承载归属；他人 cursor 不会泄露他人数据。"""
    _seed(client, peer["header"], 3, start=100)
    foreign = _list(client, peer["header"]).get_json()["data"]["items"][0]
    cursor = encode_cursor(datetime.strptime(foreign["recorded_at"], "%Y-%m-%d %H:%M:%S"),
                           foreign["id"])
    body = _list(client, user["header"], cursor=cursor).get_json()["data"]
    assert body["items"] == []


def test_r02_half_open_interval(client, user):
    """D：时间范围为**半开区间** ``[start, end)``。"""
    _seed(client, user["header"], 5)                       # 08:00 ~ 08:04
    body = _list(client, user["header"],
                 start="2026-08-01 08:01:00", end="2026-08-01 08:04:00").get_json()["data"]
    stamps = [it["recorded_at"] for it in body["items"]]
    assert stamps == ["2026-08-01 08:03:00", "2026-08-01 08:02:00", "2026-08-01 08:01:00"]
    # 等价闭区间会多一条 —— 证明 end 不含
    assert "2026-08-01 08:04:00" not in stamps
    assert "2026-08-01 08:00:00" not in stamps


def test_r02_date_only_bounds_accepted(client, user):
    """D：``start`` / ``end`` 接受 ``YYYY-MM-DD``。"""
    _seed(client, user["header"], 3)
    body = _list(client, user["header"], start="2026-08-01", end="2026-08-02").get_json()["data"]
    assert len(body["items"]) == 3


def test_r02_start_not_less_than_end_rejected(client, user):
    """D：``start >= end`` → 400。"""
    for start, end in (("2026-08-02", "2026-08-01"), ("2026-08-01", "2026-08-01")):
        resp = _list(client, user["header"], start=start, end=end)
        assert resp.status_code == 400, resp.get_json()
        assert resp.get_json()["code"] == ErrorCode.INVALID_PARAM


def test_r02_malformed_bounds_rejected(client, user):
    """D：非法时间格式 → 400（不做模糊解析）。"""
    for bad in ("2026/08/01", "08-01-2026", "2026-08-01T08:00:00Z"):
        assert _list(client, user["header"], start=bad).status_code == 400, bad


def test_r02_metric_type_filter(client, user):
    """D：按 ``metric_type`` 筛选；非法值 → 400。"""
    _seed(client, user["header"], 2)
    _seed(client, user["header"], 3, metric="water", start=60)
    assert len(_list(client, user["header"], metric_type="water").get_json()["data"]["items"]) == 3
    assert len(_list(client, user["header"], metric_type="weight").get_json()["data"]["items"]) == 2
    assert _list(client, user["header"], metric_type="bmi").status_code == 400


def test_r02_soft_deleted_hidden(client, user):
    """M：软删记录在列表中不可见，且不影响 ``count``。"""
    _seed(client, user["header"], 3)
    target = _list(client, user["header"]).get_json()["data"]["items"][0]
    assert client.delete(f"{API}/records/{target['id']}",
                         headers=user["header"]).status_code == 200
    body = _list(client, user["header"]).get_json()["data"]
    assert len(body["items"]) == 2
    assert target["id"] not in [it["id"] for it in body["items"]]
    assert _count(client, user["header"]).get_json()["data"]["count"] == 2


def test_r02_only_own_data(client, user, peer):
    """D：只返回本人数据（跨用户零泄露）。"""
    _seed(client, user["header"], 2)
    _seed(client, peer["header"], 4, start=200)
    assert len(_list(client, user["header"]).get_json()["data"]["items"]) == 2
    assert len(_list(client, peer["header"]).get_json()["data"]["items"]) == 4


def test_r02_requires_auth(client):
    """L：R-02 必须认证。"""
    assert client.get(f"{API}/records").status_code == 401


# ════════════════════════════════════════════════════════════════════
# R-07 计数
# ════════════════════════════════════════════════════════════════════
def test_r07_count_shape_and_soft_delete(client, user):
    """E：仅返回 ``count``；软删不计入。"""
    _seed(client, user["header"], 4)
    body = _count(client, user["header"]).get_json()["data"]
    assert body == {"count": 4}

    target = _list(client, user["header"]).get_json()["data"]["items"][0]
    client.delete(f"{API}/records/{target['id']}", headers=user["header"])
    assert _count(client, user["header"]).get_json()["data"]["count"] == 3


def test_r07_count_filters(client, user):
    """E：支持 ``metric_type`` + 半开区间条件。"""
    _seed(client, user["header"], 5)
    _seed(client, user["header"], 3, metric="water", start=60)

    assert _count(client, user["header"], metric_type="water").get_json()["data"]["count"] == 3
    assert _count(client, user["header"],
                  start="2026-08-01 08:00:00",
                  end="2026-08-01 08:02:00").get_json()["data"]["count"] == 2


def test_r07_count_invalid_params(client, user):
    """E：非法参数与列表接口同一口径（400）。"""
    assert _count(client, user["header"], metric_type="bmi").status_code == 400
    assert _count(client, user["header"],
                  start="2026-08-02", end="2026-08-01").status_code == 400


def test_r07_only_own_data(client, user, peer):
    """E：只统计当前用户，不泄露他人数据。"""
    _seed(client, user["header"], 2)
    _seed(client, peer["header"], 7, start=200)
    assert _count(client, user["header"]).get_json()["data"]["count"] == 2
    assert _count(client, peer["header"]).get_json()["data"]["count"] == 7


def test_r07_requires_auth(client):
    """L：R-07 必须认证。"""
    assert client.get(f"{API}/records/count").status_code == 401
