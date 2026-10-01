# -*- coding: utf-8 -*-
"""S2 第五批（S-01 / S-02 / S-03）真实 HTTP 联调冒烟（双账号 · 造数 · 断言 · 清理）。

用法::

    cd C:\\Users\\Toporder-WS\\Desktop\\Demo
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch5_http_smoke.py
    backend\\.venv\\Scripts\\python.exe scripts\\s2_batch5_http_smoke.py --port 5000

前置：后端已启动（``cd backend && .venv/Scripts/python.exe wsgi.py``）。

口径（开工方案 §十五）：
1. 注册 / 登录 ``acctest01``（本端）/ ``acctest02``（对端）；账号**存在则直接登录、不删除**；
2. 仅**本端**造数：经 **R-01 真实 HTTP** 写入跨窗口边界的记录（``start`` 当天 00:00:00、
   ``end`` 当天 23:59:59、次日 00:00:00、缺失日期、同日多条 weight / water、sleep 跨天、
   sport minutes/count、mood + tags、glucose ``attr_1``、heart ``resting``、bp 双值），
   并建 ``weight`` / ``water`` 目标（供 ``target_line`` / ``reached_rate_percent``）；
3. 对 3 接口逐项断言（``chart``、``points`` 字段、``insufficient_data``、``window`` 边界、
   ``target_line``、``group_by``、``weekly``、``tag_distribution``、5 项数字与差异字段）；
4. 隔离：对端调用三接口，断言**看不到**本端任何数据；
5. 参数校验：``window=15``、``metric_type=x``、``group_by`` 非法、``user_id`` 注入、无 Token；
6. 收尾：``finally`` 清理本次测试数据（**仅 acctest0x 范围**）。

> 脚本**自身落盘** stdout / stderr（调用方请勿使用 ``| tail`` 等本机不兼容管道）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PORT = 5000
PWD = "Kangji2026"
UA = "acctest01"
UB = "acctest02"

RESULTS: List[Tuple[str, bool, str]] = []
FAILS: List[str] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    if not ok:
        FAILS.append(f"{name}{('   -> ' + detail) if detail else ''}")


def say(text: str = "") -> None:
    print(text, flush=True)


# ════════════════════════════════════════════════════════════════════
# HTTP
# ════════════════════════════════════════════════════════════════════
class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
             token: Optional[str] = None) -> Tuple[int, Any]:
        url = self.base + path
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", "replace")
            try:
                return err.code, json.loads(raw) if raw else None
            except Exception:
                return err.code, None


def data_of(body: Any) -> Dict[str, Any]:
    return (body or {}).get("data") or {}


def code_of(body: Any) -> str:
    return (body or {}).get("code") or ""


# ════════════════════════════════════════════════════════════════════
# 时间工具（本地墙上时间，与 D-4 一致）
# ════════════════════════════════════════════════════════════════════
def stamp(day_offset: int, hour: int = 9, minute: int = 0, second: int = 0) -> str:
    day = datetime.now().date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute, second)).strftime("%Y-%m-%d %H:%M:%S")


def back(day_offset: int, hour: int, minute: int, hours: float) -> str:
    day = datetime.now().date() + timedelta(days=day_offset)
    base = datetime.combine(day, time(hour, minute, 0))
    return (base - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def day_str(day_offset: int = 0) -> str:
    return (datetime.now().date() + timedelta(days=day_offset)).isoformat()


def week_start(d: datetime) -> str:
    return (d.date() - timedelta(days=d.weekday())).isoformat()


# ════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    c = Client(f"http://{args.host}:{args.port}/api/v1")
    token_a: Optional[str] = None
    token_b: Optional[str] = None

    try:
        # ── 0. 连通性 ───────────────────────────────────────────────
        st, body = c.call("GET", "/health")
        if st != 200:
            say(f"[FATAL] 后端未就绪：GET /api/v1/health -> HTTP {st}。"
                f"请先启动：cd backend && .venv/Scripts/python.exe wsgi.py")
            return 2
        record("冒烟：GET /api/v1/health 200 OK", code_of(body) == "OK", f"HTTP {st}")

        # ── 1. 双账号 ───────────────────────────────────────────────
        def boot(user: str) -> str:
            c.call("POST", "/auth/register", {
                "username": user, "password": PWD,
                "agreement_version": "v1.0", "agreement_accepted": True,
            })
            st2, b2 = c.call("POST", "/auth/login", {"username": user, "password": PWD})
            if st2 != 200:
                raise RuntimeError(f"账号 {user} 登录失败 HTTP {st2} {code_of(b2)}")
            return data_of(b2)["tokens"]["access_token"]

        token_a = boot(UA)
        token_b = boot(UB)
        record("双账号就绪（acctest01 本端 / acctest02 对端）", bool(token_a and token_b))

        # 预清理（保证可重复运行，不叠加）
        c.call("GET", "/home/overview", None, token_a)  # noqa: 预热
        pre_a = purge(c, token_a)
        pre_b = purge(c, token_b)
        say(f"  预清理：本端 {pre_a} 条 / 对端 {pre_b} 条")

        # ── 2. 空态 ─────────────────────────────────────────────────
        st, body = c.call("GET", "/home/overview", None, token_a)
        d = data_of(body)
        record("S-01 空态 200", st == 200, f"HTTP {st}")
        record("S-01 空态顶层恰 5 字段", sorted(d) ==
               ["date", "goals", "recent_records", "reminder_fallback", "today"], str(sorted(d)))
        record("S-01 today 空态 {0, []}", d.get("today") ==
               {"record_count": 0, "metric_types_recorded": []}, str(d.get("today")))
        record("S-01 reminder_fallback 固定占位语义",
               d.get("reminder_fallback") == {
                   "source": "local",
                   "note": "N/A（提醒兜底计数由客户端本地计算，服务端不提供）"},
               str(d.get("reminder_fallback")))

        # ── 3. 鉴权 / 守卫 ──────────────────────────────────────────
        probes = [("/home/overview", ""), ("/stats/trend", "?metric_type=water"),
                  ("/stats/summary", "?metric_type=water")]
        bad = [p for p, q in probes if c.call("GET", p + q)[0] != 401]
        record("三接口 无 Token -> 401", not bad, str(bad))

        bad = [p for p, q in probes
               if c.call("GET", p + q + ("&" if q else "?") + "user_id=1")[0] != 400]
        record("三接口 query 携带 user_id -> 400 INVALID_PARAM", not bad, str(bad))
        bad = [p for p, q in probes if c.call("GET", p + q, {"user_id": 1})[0] != 400]
        record("三接口 body 携带 user_id -> 400 INVALID_PARAM", not bad, str(bad))

        # ── 4. 造数（仅本端） ───────────────────────────────────────
        rec_ids: List[int] = []
        goal_ids: List[int] = []

        def add_rec(**payload: Any) -> int:
            st2, b2 = c.call("POST", "/records", payload, token_a)
            if st2 != 201:
                raise RuntimeError(f"R-01 写入失败 HTTP {st2} {code_of(b2)} payload={payload}")
            rid = data_of(b2)["record"]["id"]
            rec_ids.append(rid)
            return rid

        def add_goal(**payload: Any) -> int:
            st2, b2 = c.call("POST", "/goals", payload, token_a)
            if st2 != 201:
                raise RuntimeError(f"G-02 建目标失败 HTTP {st2} {code_of(b2)} payload={payload}")
            gid = data_of(b2)["goal"]["id"]
            goal_ids.append(gid)
            return gid

        add_rec(metric_type="weight", value_1=72.0, recorded_at=stamp(-6, 9))
        add_rec(metric_type="weight", value_1=71.5, recorded_at=stamp(-4, 9))
        add_rec(metric_type="weight", value_1=70.50, recorded_at=stamp(-3, 8))
        add_rec(metric_type="weight", value_1=71.50, recorded_at=stamp(-3, 20))
        add_rec(metric_type="weight", value_1=71.00, recorded_at=stamp(-2, 9))
        add_rec(metric_type="water", value_1=2000, recorded_at=stamp(-7, 23, 59, 59))
        add_rec(metric_type="water", value_1=1000, recorded_at=stamp(-6, 0, 0, 0))
        add_rec(metric_type="water", value_1=300, recorded_at=stamp(-5, 0, 0, 0))
        add_rec(metric_type="water", value_1=1500, recorded_at=stamp(-2, 9))
        add_rec(metric_type="water", value_1=900, recorded_at=stamp(-2, 21))
        add_rec(metric_type="water", value_1=300, recorded_at=stamp(-1, 9))
        add_rec(metric_type="water", value_1=500, recorded_at=stamp(-1, 23, 59, 59))
        add_rec(metric_type="bp", value_1=120, value_2=80, recorded_at=stamp(-5, 8))
        add_rec(metric_type="bp", value_1=130, value_2=90, recorded_at=stamp(-2, 8))
        add_rec(metric_type="heart", value_1=60, attr_1="resting", recorded_at=stamp(-2, 8))
        add_rec(metric_type="heart", value_1=80, recorded_at=stamp(-2, 20))
        add_rec(metric_type="glucose", value_1=5.5, attr_1="fasting", recorded_at=stamp(-2, 7))
        add_rec(metric_type="glucose", value_1=6.5, attr_1="fasting", recorded_at=stamp(-1, 7))
        add_rec(metric_type="glucose", value_1=8.0, attr_1="after_meal_2h", recorded_at=stamp(-1, 20))
        add_rec(metric_type="sleep", value_1=5, time_start=back(-2, 7, 0, 8.5),
                recorded_at=stamp(-2, 7))
        add_rec(metric_type="sleep", value_1=4, time_start=back(-1, 7, 0, 6.5),
                recorded_at=stamp(-1, 7))
        add_rec(metric_type="sport", value_1=30, attr_1="running", recorded_at=stamp(-1, 9))
        add_rec(metric_type="sport", value_1=45, attr_1="walking", recorded_at=stamp(-1, 10))
        add_rec(metric_type="mood", value_1=4, tags=["relaxed"], recorded_at=stamp(-2, 9))
        add_rec(metric_type="mood", value_1=2, tags=["tired", "relaxed"], recorded_at=stamp(-1, 9))
        record("造数：本端写入 25 条记录", len(rec_ids) == 25, str(len(rec_ids)))

        water_goal = add_goal(goal_type="water", target_value=2000)
        weight_goal = add_goal(goal_type="weight", target_value=68.0, start_weight_kg=72.5)
        add_goal(goal_type="sleep", target_value=8)
        record("造数：本端 3 个自设目标", len(goal_ids) == 3, str(len(goal_ids)))

        # ── 5. S-02 断言 ────────────────────────────────────────────
        def trend(**q: Any) -> Dict[str, Any]:
            qs = "&".join(f"{k}={v}" for k, v in q.items())
            _st, b = c.call("GET", "/stats/trend" + (("?" + qs) if qs else ""), None, token_a)
            return data_of(b)

        def summary(**q: Any) -> Dict[str, Any]:
            qs = "&".join(f"{k}={v}" for k, v in q.items())
            _st, b = c.call("GET", "/stats/summary" + (("?" + qs) if qs else ""), None, token_a)
            return data_of(b)

        w = trend(metric_type="water")
        record("S-02 water 骨架 7 键", sorted(w) ==
               ["chart", "insufficient_data", "metric_type", "points", "target_line", "unit", "window"],
               str(sorted(w)))
        record("S-02 water unit/chart", (w["unit"], w["chart"]) == ("ml", "bar"),
               f"{w.get('unit')}/{w.get('chart')}")
        record("S-02 window 默认 7", w["window"] ==
               {"days": 7, "start": day_str(-6), "end": day_str(0)}, str(w["window"]))
        record("S-02 water points（半开边界 + 同日累计）", w["points"] == [
            {"date": day_str(-6), "total_ml": 1000},
            {"date": day_str(-5), "total_ml": 300},
            {"date": day_str(-2), "total_ml": 2400},
            {"date": day_str(-1), "total_ml": 800},
        ], str(w["points"]))
        record("S-02 insufficient_data = false", w["insufficient_data"] is False)
        record("S-02 target_line（water 2000）", w["target_line"] ==
               {"value": 2000, "unit": "ml", "source": "health_goal", "goal_id": water_goal},
               str(w["target_line"]))

        record("S-02 window=30 start=end-29", trend(metric_type="water", window=30)["window"] ==
               {"days": 30, "start": day_str(-29), "end": day_str(0)})
        record("S-02 window=90 start=end-89", trend(metric_type="water", window=90)["window"] ==
               {"days": 90, "start": day_str(-89), "end": day_str(0)})
        record("S-02 end=过去日 半开窗口（end=d-3 -> start=d-9，d-7 23:59:59 重新纳入）",
               trend(metric_type="water", end=day_str(-3))["points"] ==
               [{"date": day_str(-7), "total_ml": 2000},
                {"date": day_str(-6), "total_ml": 1000},
                {"date": day_str(-5), "total_ml": 300}],
               str(trend(metric_type="water", end=day_str(-3))["points"]))
        fut = trend(metric_type="water", end=day_str(100))
        record("S-02 end=未来日（T-4）-> 空数据 200", fut["points"] == [] and
               fut["insufficient_data"] is True, str(fut["points"]))

        wt = trend(metric_type="weight")
        record("S-02 weight 当日取最后一次 + 整数归一", wt["points"] == [
            {"date": day_str(-6), "value": 72},
            {"date": day_str(-4), "value": 71.5},
            {"date": day_str(-3), "value": 71.5},
            {"date": day_str(-2), "value": 71},
        ], str(wt["points"]))
        record("S-02 weight 整数值为 int",
               isinstance([p for p in wt["points"] if p["date"] == day_str(-2)][0]["value"], int))
        record("S-02 weight target_line（68 kg）", wt["target_line"] ==
               {"value": 68, "unit": "kg", "source": "health_goal", "goal_id": weight_goal},
               str(wt["target_line"]))

        bp = trend(metric_type="bp")
        record("S-02 bp 双值均值", bp["points"] == [
            {"date": day_str(-5), "systolic": 120, "diastolic": 80},
            {"date": day_str(-2), "systolic": 130, "diastolic": 90}], str(bp["points"]))
        bp1 = trend(metric_type="bp", end=day_str(-3))
        record("S-02 bp 单点 insufficient_data = true",
               len(bp1["points"]) == 1 and bp1["insufficient_data"] is True, str(bp1["points"]))

        record("S-02 heart 当日均值", trend(metric_type="heart")["points"] ==
               [{"date": day_str(-2), "value": 70}])
        gl = trend(metric_type="glucose")
        record("S-02 glucose 无 group_by 时不返 groups", "groups" not in gl)
        record("S-02 glucose 当日均分", gl["points"] == [
            {"date": day_str(-2), "value": 5.5}, {"date": day_str(-1), "value": 7.25}],
            str(gl["points"]))
        record("S-02 glucose groups 固定序", trend(metric_type="glucose", group_by="timing")["groups"] ==
               [{"timing": "fasting", "value": 6}, {"timing": "after_meal_2h", "value": 8}],
               str(trend(metric_type="glucose", group_by="timing").get("groups")))
        sl = trend(metric_type="sleep")
        record("S-02 sleep 累计时长 + 质量均分", sl["points"] == [
            {"date": day_str(-2), "duration_hours": 8.5, "quality": 5},
            {"date": day_str(-1), "duration_hours": 6.5, "quality": 4}], str(sl["points"]))
        sp = trend(metric_type="sport")
        record("S-02 sport minutes/count", sp["points"] ==
               [{"date": day_str(-1), "minutes": 75, "count": 2}], str(sp["points"]))
        weekly = sp.get("weekly") or []
        monday = bool(weekly) and datetime.strptime(weekly[0]["week_start"], "%Y-%m-%d").weekday() == 0
        record("S-02 sport weekly（week_start 周一）", len(weekly) == 1 and monday and
               weekly[0]["minutes"] == 75 and weekly[0]["count"] == 2, str(weekly))
        md = trend(metric_type="mood")
        record("S-02 mood 均分", md["points"] == [
            {"date": day_str(-2), "value": 4}, {"date": day_str(-1), "value": 2}], str(md["points"]))
        record("S-02 mood tag_distribution 固定序", md["tag_distribution"] ==
               [{"tag": "tired", "count": 1}, {"tag": "relaxed", "count": 2}],
               str(md.get("tag_distribution")))

        chart = {"weight": "line", "bp": "line", "heart": "line", "glucose": "line",
                 "sleep": "bar", "water": "bar", "sport": "bar", "mood": "line"}
        wrong = {m: trend(metric_type=m)["chart"] for m, v in chart.items()
                 if trend(metric_type=m)["chart"] != v}
        record("S-02 chart 逐指标正确", not wrong, str(wrong))

        others = ["bp", "heart", "glucose", "sleep", "sport", "mood"]
        bad = [m for m in others if "target_line" in trend(metric_type=m)]
        record("S-02 非 weight/water 无 target_line 键", not bad, str(bad))

        # ── 6. S-03 断言 ────────────────────────────────────────────
        wt = summary(metric_type="weight")
        b = wt["summary"]
        record("S-03 weight 通用 5 项", (
            b["average"] == 71.5
            and b["change"] == {"from": 72, "to": 71, "delta": -1,
                                "from_date": day_str(-6), "to_date": day_str(-2)}
            and b["max"] == {"value": 72, "date": day_str(-6)}
            and b["min"] == {"value": 71, "date": day_str(-2)}
            and b["recorded_days"] == {"recorded": 4, "total": 7, "percent": 57.1}
        ), str(b))
        record("S-03 weight distance_to_target=3 / reached_rate null",
               b["distance_to_target"] == 3 and b["reached_rate_percent"] is None, str(b))

        b = summary(metric_type="bp")["summary"]
        record("S-03 bp 差异字段 + max/min 含收缩舒张",
               b["average_systolic"] == 125 and b["average_diastolic"] == 85
               and b["measure_count"] == 2
               and b["max"] == {"systolic": 130, "diastolic": 90, "date": day_str(-2)}
               and b["min"] == {"systolic": 120, "diastolic": 80, "date": day_str(-5)}
               and b["reached_rate_percent"] is None, str(b))

        b = summary(metric_type="heart")["summary"]
        record("S-03 heart resting_average/average",
               b["resting_average"] == 60 and b["average"] == 70, str(b))
        b = summary(metric_type="glucose")["summary"]
        record("S-03 glucose fasting/after_meal/measure_count",
               b["average_fasting"] == 6 and b["average_after_meal"] == 8
               and b["measure_count"] == 3, str(b))
        b = summary(metric_type="sleep")["summary"]
        record("S-03 sleep 字段 + 达标率 50.0",
               b["average_duration_hours"] == 7.5 and b["average_quality"] == 4.5
               and b["longest"] == {"value": 8.5, "date": day_str(-2)}
               and b["shortest"] == {"value": 6.5, "date": day_str(-1)}
               and b["reached_rate_percent"] == 50.0, str(b))
        b = summary(metric_type="water")["summary"]
        record("S-03 water 字段 + 达标率 25.0 + 连续 1 天",
               b["average"] == 1125 and b["daily_average_ml"] == 1125
               and b["reached_day_count"] == 1 and b["reached_rate_percent"] == 25.0
               and b["longest_streak_days"] == 1, str(b))
        b = summary(metric_type="sport")["summary"]
        weeks = len({week_start(datetime.now() - timedelta(days=i)) for i in range(7)})
        record("S-03 sport 字段 + 周均",
               b["total_minutes"] == 75 and b["daily_average_minutes"] == 75
               and b["session_count"] == 2 and b["reached_week_count"] == 0
               and b["weekly_average_minutes"] == 75 / weeks, str(b))
        b = summary(metric_type="mood")["summary"]
        record("S-03 mood 字段 + 标签分布",
               b["average_score"] == 3 and b["best_day"] == {"value": 4, "date": day_str(-2)}
               and b["worst_day"] == {"value": 2, "date": day_str(-1)}
               and b["tag_distribution"] == [{"tag": "tired", "count": 1},
                                             {"tag": "relaxed", "count": 2}]
               and b["reached_rate_percent"] is None, str(b))

        b = summary(metric_type="water", end=day_str(-10))
        record("S-03 空窗口 5 项全 null + recorded_days",
               b["summary"]["average"] is None and b["summary"]["change"] is None
               and b["summary"]["max"] is None and b["summary"]["min"] is None
               and b["summary"]["recorded_days"] == {"recorded": 0, "total": 7, "percent": 0.0},
               str(b["summary"]))
        tw = trend(metric_type="weight", window=30)["window"]
        sw = summary(metric_type="weight", window=30)["window"]
        record("S-03 窗口规则与 S-02 一致", tw == sw, f"{tw} vs {sw}")

        # ── 7. 参数校验 ─────────────────────────────────────────────
        def bad_req(path: str, q: str, expect: int, expect_code: str) -> bool:
            st2, b2 = c.call("GET", path + q, None, token_a)
            return st2 == expect and code_of(b2) == expect_code

        bad_metric = [""] + ["blood", "WATER", "bp2"]
        miss = not bad_req("/stats/trend", "", 400, "INVALID_PARAM")
        miss = miss or any(not bad_req("/stats/trend", "?metric_type=" + m, 400, "INVALID_PARAM")
                           for m in ["blood", "WATER", "bp2"])
        record("S-02/S-03 metric_type 必填且仅 8 类 -> 400", not miss)
        wins = ["0", "1", "14", "31", "91", "-7", "abc", "7.5"]
        record("S-02 window 仅 7/30/90 -> 400",
               all(bad_req("/stats/trend", "?metric_type=water&window=" + v, 400, "INVALID_PARAM")
                   for v in wins))
        ends = ["2026-9-1", "2026/09/01", "abc", "2026-13-01"]
        record("S-02 end 非法格式 -> 400",
               all(bad_req("/stats/trend", "?metric_type=water&end=" + v, 400, "INVALID_PARAM")
                   for v in ends))
        gbs = ["?metric_type=water&group_by=timing", "?metric_type=glucose&group_by=tag",
               "?metric_type=mood&group_by=timing", "?metric_type=water&group_by=tag",
               "?metric_type=glucose&group_by=xyz"]
        record("S-02 非法 group_by 组合 -> 400",
               all(bad_req("/stats/trend", q, 400, "INVALID_PARAM") for q in gbs))
        record("S-03 参数校验 -> 400",
               bad_req("/stats/summary", "", 400, "INVALID_PARAM")
               and bad_req("/stats/summary", "?metric_type=xyz", 400, "INVALID_PARAM")
               and bad_req("/stats/summary", "?metric_type=water&window=15", 400, "INVALID_PARAM"))
        record("S-01 非法 tz -> 400", bad_req("/home/overview", "?tz_offset_minutes=abc",
                                             400, "INVALID_PARAM"))

        # ── 8. S-01 有数据 + 隔离 ───────────────────────────────────
        add_rec(metric_type="weight", value_1=70.8, recorded_at=stamp(0, 9))
        add_rec(metric_type="water", value_1=500, recorded_at=stamp(0, 10))
        add_rec(metric_type="mood", value_1=3, tags=["focused"], recorded_at=stamp(0, 11))

        _st, b2 = c.call("GET", "/home/overview", None, token_a)
        d = data_of(b2)
        record("S-01 today 仅统计今日 = 3",
               d["today"]["record_count"] == 3, str(d["today"]))
        record("S-01 metric_types_recorded 固定序",
               d["today"]["metric_types_recorded"] == ["weight", "water", "mood"],
               str(d["today"]["metric_types_recorded"]))
        recs = d["recent_records"]
        record("S-01 recent_records 上限 10 条", len(recs) == 10, str(len(recs)))
        record("S-01 recent_records DESC",
               [r["recorded_at"] for r in recs] ==
               sorted([r["recorded_at"] for r in recs], reverse=True))
        record("S-01 recent_records 恰 8 字段", sorted(recs[0]) ==
               ["id", "metric_type", "note", "recorded_at", "tags", "time_start", "unit", "value_1"],
               str(sorted(recs[0])))
        mood_rec = next((r for r in recs if r["metric_type"] == "mood"), None)
        record("S-01 mood 记录带 tags",
               mood_rec is not None and "focused" in (mood_rec.get("tags") or []),
               str(mood_rec.get("tags") if mood_rec else None))
        goals = d["goals"]
        record("S-01 goals 顺序 goal_type ASC",
               [g["goal_type"] for g in goals] == ["sleep", "water", "weight"],
               str([g["goal_type"] for g in goals]))
        record("S-01 goals 每项恰 8 字段", all(sorted(g) ==
               ["current_value", "goal_id", "goal_type", "is_reached", "progress_percent",
                "remaining_text", "target_value", "unit"] for g in goals))
        water_g = next((g for g in goals if g["goal_type"] == "water"), None)
        record("S-01 water 目标完成度 500/2000 = 25.0",
               water_g is not None and water_g["target_value"] == 2000
               and water_g["current_value"] == 500
               and water_g["progress_percent"] == 25.0, str(water_g))

        d_b = data_of(c.call("GET", "/home/overview", None, token_b)[1])
        t_b = trend_b(c, token_b, "water")
        s_b = summary_b(c, token_b, "water")
        record("隔离：对端 S-01 空", d_b["today"]["record_count"] == 0
               and d_b["goals"] == [] and d_b["recent_records"] == [], str(d_b["today"]))
        record("隔离：对端 S-02 points 空", t_b["points"] == [], str(t_b["points"]))
        record("隔离：对端 S-03 average null", s_b["summary"]["average"] is None)

        # ── 9. 软删过滤 ─────────────────────────────────────────────
        victim = add_rec(metric_type="water", value_1=700, recorded_at=stamp(-4, 9))
        add_rec(metric_type="water", value_1=300, recorded_at=stamp(-4, 21))
        p0 = next((p for p in trend(metric_type="water")["points"] if p["date"] == day_str(-4)), None)
        record("软删前 d-4 累计 1000", p0 == {"date": day_str(-4), "total_ml": 1000}, str(p0))
        st2, _b2 = c.call("DELETE", f"/records/{victim}", None, token_a)
        record("软删请求 200", st2 == 200, f"HTTP {st2}")
        rec_ids.remove(victim)
        p1 = next((p for p in trend(metric_type="water")["points"] if p["date"] == day_str(-4)), None)
        record("软删后 d-4 累计 300", p1 == {"date": day_str(-4), "total_ml": 300}, str(p1))

    except Exception as exc:  # noqa: BLE001
        record("顶层执行异常", False, f"{type(exc).__name__}: {exc}")
        import traceback
        say(traceback.format_exc())
    finally:
        # ── 10. 清理（仅 acctest0x 范围） ──────────────────────────
        try:
            if token_a:
                n1 = purge(c, token_a)
                say(f"  清理：本端 {n1} 条")
        except Exception as exc:  # noqa: BLE001
            say(f"  [WARN] 本端清理异常：{exc}")
        try:
            if token_b:
                n2 = purge(c, token_b)
                say(f"  清理：对端 {n2} 条")
        except Exception as exc:  # noqa: BLE001
            say(f"  [WARN] 对端清理异常：{exc}")

        passed = sum(1 for _n, ok_, _d in RESULTS if ok_)
        total = len(RESULTS)
        say()
        say("=" * 72)
        for name, ok_, detail in RESULTS:
            say(f"  {'PASS' if ok_ else 'FAIL'}  {name}" + (f"   -> {detail}" if (detail and not ok_) else ""))
        say("-" * 72)
        say(f"  合计 {passed}/{total} PASS，{total - passed} FAIL")
        say(f"  结论：{'全部通过' if passed == total else '存在失败项'}")
        say("=" * 72)

    return 0 if not FAILS else 1


# ════════════════════════════════════════════════════════════════════
# 对端只读工具 / 清理
# ════════════════════════════════════════════════════════════════════
def trend_b(c: Client, token: str, metric: str) -> Dict[str, Any]:
    return data_of(c.call("GET", f"/stats/trend?metric_type={metric}", None, token)[1])


def summary_b(c: Client, token: str, metric: str) -> Dict[str, Any]:
    return data_of(c.call("GET", f"/stats/summary?metric_type={metric}", None, token)[1])


def purge(c: Client, token: str) -> int:
    """清理该账号全部记录与目标（仅用于测试账号）。"""
    n = 0
    for _ in range(50):
        _st, body = c.call("GET", "/records?limit=100", None, token)
        items = data_of(body).get("items") or []
        if not items:
            break
        for it in items:
            c.call("DELETE", f"/records/{it['id']}", None, token)
            n += 1
        if not data_of(body).get("has_more"):
            break
    _st, body = c.call("GET", "/goals?include_paused=true", None, token)
    for g in (data_of(body).get("items") or []):
        c.call("DELETE", f"/goals/{g['id']}", None, token)
        n += 1
    return n


if __name__ == "__main__":
    raise SystemExit(main())
