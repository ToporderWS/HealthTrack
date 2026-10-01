# -*- coding: utf-8 -*-
"""S2 第六批 E-04（``GET /api/v1/exports``）验收用例。

覆盖：S 列表 / T 分页边界 / U 用户隔离 / V 排序稳定性 / 字段暴露面控制。
"""
from __future__ import annotations

from tests.batch6.conftest import (
    dt_before,
    insert_job,
    list_exports,
    new_export,
)

ITEM_KEYS = {
    "export_id", "format", "status", "record_count", "file_size_bytes",
    "download_expires_at", "purge_at", "downloaded_at", "created_at",
}


def _list(client, header, **query):
    resp = list_exports(client, header, **query)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["code"] == "OK"
    return body["data"]


# ════════════════════════════════════════════════════════════════════
# S —— 列表
# ════════════════════════════════════════════════════════════════════
def test_e04_empty_list(client, user):
    """S：无任务 → ``items: []`` / ``has_more: false`` / ``next_cursor: null``。"""
    data = _list(client, user["header"])
    assert data == {"items": [], "next_cursor": None, "has_more": False}


def test_e04_list_structure(client, exporter):
    """S：``items[]`` = E-02 结构**去除 ``file_token``**；**不返回** ``total`` / ``file_path``。"""
    new_export(client, exporter["header"], format="csv", password=exporter["password"])
    data = _list(client, exporter["header"])

    assert set(data.keys()) == {"items", "next_cursor", "has_more"}
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert set(item.keys()) == ITEM_KEYS, item
    assert "file_token" not in item and "file_path" not in item
    assert "total" not in data
    assert item["status"] == "ready" and item["record_count"] == 3


def test_e04_order_created_at_desc(client, user):
    """V：固定排序 ``created_at DESC``（**不支持自定义**）；同秒以 ``id DESC`` 稳定。"""
    ids = [insert_job(user["user_id"], created_at=dt_before(minutes=10 * (i + 1)))
           for i in range(5)]
    data = _list(client, user["header"])
    assert [item["export_id"] for item in data["items"]] == ids   # 越晚创建越靠前

    stamp = dt_before(minutes=1)                                  # 比上面 5 条都新，且三者同秒
    same_second = [insert_job(user["user_id"], created_at=stamp) for _ in range(3)]
    listed = [item["export_id"] for item in _list(client, user["header"])["items"]]
    assert listed[:3] == sorted(same_second, reverse=True)


def test_e04_status_is_effective(client, user):
    """S：列表中的 ``status`` 为**动态判定**结果（过期即 ``expired`` / ``purged``）。"""
    insert_job(user["user_id"], status="ready",
               download_expires_at=dt_before(minutes=1), purge_at=dt_before(days=-1))
    insert_job(user["user_id"], status="ready",
               download_expires_at=dt_before(minutes=2), purge_at=dt_before(minutes=1))
    statuses = sorted(item["status"] for item in _list(client, user["header"])["items"])
    assert statuses == ["expired", "purged"]


# ════════════════════════════════════════════════════════════════════
# T —— 分页边界
# ════════════════════════════════════════════════════════════════════
def test_e04_limit_default_and_allowed(client, user):
    """T：``limit`` 默认 20，允许 20 / 50 / 100；其余取值 → ``400``。"""
    for i in range(25):
        insert_job(user["user_id"], created_at=dt_before(minutes=i + 1))

    assert len(_list(client, user["header"])["items"]) == 20                # 默认
    assert len(_list(client, user["header"], limit=50)["items"]) == 25
    assert len(_list(client, user["header"], limit=100)["items"]) == 25
    for bad in (7, 0, -1, 101, 1000, "abc"):
        resp = list_exports(client, user["header"], limit=bad)
        assert resp.status_code == 400, bad
        assert resp.get_json()["code"] == "INVALID_PARAM"


def test_e04_cursor_pagination_no_overlap(client, user):
    """T：游标翻页 —— 两页不重叠、不遗漏；末页 ``has_more=false``。"""
    ids = [insert_job(user["user_id"], created_at=dt_before(minutes=i + 1))
           for i in range(25)]

    page1 = _list(client, user["header"], limit=20)
    assert page1["has_more"] is True
    assert page1["next_cursor"]

    page2 = _list(client, user["header"], limit=20, cursor=page1["next_cursor"])
    assert page2["has_more"] is False
    assert page2["next_cursor"] is None

    got = [item["export_id"] for item in page1["items"]] + \
          [item["export_id"] for item in page2["items"]]
    assert got == ids
    assert len(set(got)) == 25


def test_e04_invalid_cursor(client, user):
    """T：非法 ``cursor`` → ``400``（**不回退为从头发**）。"""
    for bad in ("not-a-cursor", "!!!!", "eyJ0IjoxfQ"):
        resp = list_exports(client, user["header"], cursor=bad)
        assert resp.status_code == 400, bad
        assert resp.get_json()["code"] == "INVALID_PARAM"


# ════════════════════════════════════════════════════════════════════
# U —— 用户隔离
# ════════════════════════════════════════════════════════════════════
def test_e04_user_isolation(client, exporter, peer):
    """U：列表**只含本人**任务（他人任务不可见）。"""
    mine = new_export(client, exporter["header"], format="csv",
                      password=exporter["password"])["export_id"]
    theirs = insert_job(peer["user_id"])

    mine_list = _list(client, exporter["header"])
    peer_list = _list(client, peer["header"])

    assert [i["export_id"] for i in mine_list["items"]] == [int(mine)]
    assert [i["export_id"] for i in peer_list["items"]] == [theirs]


def test_e04_no_user_id_leak(client, exporter):
    """U：列表载荷**不含** ``user_id`` / 内部归属字段 / ``file_path``。"""
    new_export(client, exporter["header"], format="csv", password=exporter["password"])
    text = list_exports(client, exporter["header"]).get_data(as_text=True)
    assert "user_id" not in text
    assert "file_path" not in text
