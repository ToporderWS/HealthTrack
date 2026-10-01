# -*- coding: utf-8 -*-
"""B1-R-FIX · 测试安全 —— **公共安全守卫**（四重保护的执行体）。

设计目标（S2 / S3 / 额外硬保护 1~6）
------------------------------------
把原先散布在 8 个 ``conftest.py`` 里的 cleanup 机制，**统一收敛到一个咽喉点**：
所有 DELETE 都会经过本模块安装的 SQLAlchemy **引擎级** ``before_execute`` 监听器。

四重保护
--------
============  ====================================================================
**D0**        专用测试库。pytest **只能**连 ``kangji_healthtrack_test``：
              ``force_test_database()`` 在配置加载前钉死 ``MYSQL_DB``；
              ``preflight_check()`` 在会话启动时校验；
              ``connect`` 监听器在**每一次物理建连**时校验 ``SELECT DATABASE()``。
              任一不符 ⇒ ``TestSafetyViolation``（**FAIL-CLOSED，绝不 fallback**）。
**C**         本次创建集合。删除前先算出「这条 DELETE 会删掉哪些行」（同条件 SELECT），
              逐行要求 ``id > 会话水位线`` **或** 显式登记在 ``created_ids`` 中。
              ⚠️ **O-TBA-2（FAIL-CLOSED）**：水位线**取不到 ≠ 0**。取不到时该表
              **缺键**（= 未知）⇒ C 层**一律拒绝**（显式登记除外）；绝不降级为
              「无保护」。`rid <= 0` 对正常正整数主键恒为 False —— 那正是旧实现
              把「取不到」误当「空表」而静默跳过 C 层的成因。
**A**         denylist。命中 ``PROTECTED_*`` / ``PERMANENT_DENYLIST_*`` 的 id 或
              用户名，**或目标行属于受保护账号** ⇒ 无条件否决。
              ⚠️ **id 仅当在本库中以该受保护用户名真实存在时**才计入
              （``resolve_live_identity_ids``：裸数字不是身份，实测 tst 账号
              会漂移到 4833~4839；见 O-TBA-1 第二处）。
**B**         本批独占前缀。前缀**仅作辅助定位**，**绝不单独构成删除依据**
              （代码层面：``evaluate_candidates`` 从不需要前缀即可判定）。
============  ====================================================================

**为什么这不是「前缀清扫的兜底」**
----------------------------------
反过来：本守卫的判定**不依赖前缀**。它问的是「这一行在本次会话开始前就存在吗？
它属于受保护对象吗？」——只要任一答案为「是」，即 **ABORT，不删除**。
因此即便某个旧 cleanup 仍写着 ``username LIKE 'tst%'``，
它也**无法**删掉任何会话开始前已存在的行（B1 事故里被删的
``tst35ro1`` / ``tstd02`` 正是「前缀命中且已存在」，本守卫会直接否决）。

**失败语义**
------------
- 否决 ⇒ 抛 ``TestSafetyViolation``，**该 DELETE 不执行**，测试**响亮失败**。
- 宁可留下测试残留，也绝不误删既有数据；残留由 D0 专用库整体隔离解决。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, event, pool, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.elements import TextClause

# ── 使 ``import app`` / ``import testsafety`` 在任意调用点都成立 ──────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from testsafety import protected_assets as PA  # noqa: E402

from app.models import ALL_TABLES  # noqa: E402

TEST_DATABASE = PA.TEST_DATABASE
DEV_DATABASE = PA.DEV_DATABASE

#: 需要守卫的表 = V1.0 全部 10 张业务表（新增表自动纳入）
GUARDED_TABLES: Tuple[str, ...] = tuple(ALL_TABLES)

#: **表语义矩阵（O-TBA-1）**：候选行的 ``id`` 与用户身份同域**仅当**目标是
#: ``user_account`` —— 该表主键**就是**用户身份本身。
#: 其余 9 张表的 ``id`` 均为**各自独立的**自增主键，与 ``user_account.id``
#: 无任何语义关联（V1.0 表间 **0 外键**，见 ``app/models/__init__.py`` / S1-B §9.3）：
#: ``user_profile`` / ``health_record`` / ``record_tag`` / ``health_goal`` /
#: ``user_session`` / ``export_job`` / ``verification_code`` /
#: ``password_reset_token`` 的保护语义**只能**经 ``user_id`` 外键表达；
#: ``login_failure_state``（无 ``user_id`` 列）**只能**经 ``username`` 表达。
#: 把子表行自身 ``id`` 拿去比对受保护用户 id 只会产生**假阳性否决**
#: （O-TBA-1：``health_record.id = 4833`` 与「用户 4833」毫无关系）。
USER_IDENTITY_TABLES: Tuple[str, ...] = ("user_account",)

#: ``guard.py`` 侧硬编码的**下限**：即使有人改写 ``protected_assets.py``，
#: 只要不同步改这里，``assert_assets_intact()`` 就会失败。
#: （两处都改才能削弱 ⇒ 改动必然显式可见。）
MANDATORY_PROTECTED_USERNAMES = ("top001", "top002", "top003", "toptest1")
MANDATORY_TEST_DATABASE = "kangji_healthtrack_test"

#: 审计产物目录（工程级，随 .workbuddy 一起留痕）
AUDIT_DIR = _BACKEND_DIR.parent / ".workbuddy"
AUDIT_JSON = AUDIT_DIR / "testsafety_audit.json"
VETO_JSONL = AUDIT_DIR / "testsafety_vetoes.jsonl"

_MAX_EVENTS = 2000


class TestSafetyViolation(RuntimeError):
    """测试安全守卫否决（fail-closed）。"""


# ── 会话状态 ────────────────────────────────────────────────────────────
class _State:
    def __init__(self) -> None:
        self.installed = False
        self.session_id = uuid.uuid4().hex[:8]
        self.watermark: Dict[str, int] = {}
        self.watermark_taken = False
        #: ★ O-TBA-2：取线失败的受管表（**缺键 = 未知，绝不写 0**）。仅用于审计。
        self.watermark_failed: Dict[str, str] = {}
        self.created_ids: set = set()
        self.created_usernames: set = set()
        self.deletes_seen = 0
        self.deletes_allowed = 0
        self.vetoes: List[Dict[str, Any]] = []
        self.prefix_only_seen: List[Dict[str, Any]] = []
        self.checks: List[str] = []
        self._lock = threading.Lock()


_S = _State()


def reset() -> None:
    """仅用于自测：重置会话状态（**不卸载**已注册的监听器）。"""
    global _S
    _S = _State()


def session_id() -> str:
    return _S.session_id


# ── D0：专用测试库 ─────────────────────────────────────────────────────
def force_test_database(environ: Optional[dict] = None) -> str:
    """把 ``MYSQL_DB`` **钉死**为测试库。

    调用时机：``backend/conftest.py`` 的**模块导入期**——早于任何
    ``load_config()`` / ``create_engine()``。``app.core.config`` 使用
    ``load_dotenv(..., override=False)``，因此**已存在的环境变量优先**，
    ``.env.development`` 无法把它改回开发库。
    """
    env = os.environ if environ is None else environ
    env["MYSQL_DB"] = TEST_DATABASE
    return TEST_DATABASE


def preflight_check(environ: Optional[dict] = None) -> str:
    """会话启动前的**配置层**检查：``MYSQL_DB`` 必须是测试库。"""
    env = os.environ if environ is None else environ
    got = (env.get("MYSQL_DB") or "").strip()
    if got != TEST_DATABASE:
        raise TestSafetyViolation(
            "【D0 FAIL-CLOSED】pytest 启动前检查失败：\n"
            f"  当前 MYSQL_DB = {got!r}\n"
            f"  必须     = {TEST_DATABASE!r}\n"
            "  绝不自动 fallback 到开发库；涉及 DB 写入/删除的测试一律 ABORT。"
        )
    _S.checks.append(f"preflight: MYSQL_DB={got}")
    return got


def assert_on_test_database(conn) -> str:
    """对**已连接的** Connection 校验 ``SELECT DATABASE()``。"""
    db = conn.execute(text("SELECT DATABASE()")).scalar()
    db = "" if db is None else str(db).strip()
    if db != TEST_DATABASE:
        raise TestSafetyViolation(
            "【D0 FAIL-CLOSED】物理连接落在错误的数据库上：\n"
            f"  SELECT DATABASE() = {db!r}\n"
            f"  必须              = {TEST_DATABASE!r}\n"
            f"  开发库 {DEV_DATABASE!r} 在 pytest 下**绝不允许**被触碰。"
        )
    return db


# ── C：本次创建集合的登记接口 ──────────────────────────────────────────
def register_created_user(user_id: Optional[int] = None, username: Optional[str] = None) -> None:
    """显式登记「本轮测试自己创建」的用户（可选，水位线已能覆盖旧代码）。"""
    if user_id is not None:
        _S.created_ids.add(int(user_id))
    if username:
        _S.created_usernames.add(str(username))


def created_ids() -> frozenset:
    return frozenset(_S.created_ids)


def created_usernames() -> frozenset:
    return frozenset(_S.created_usernames)


def watermark() -> Dict[str, int]:
    return dict(_S.watermark)


# ── A：保护名单完整性 ──────────────────────────────────────────────────
def assert_assets_intact() -> str:
    """校验保护名单**未被静默削弱**（指纹 + 跨文件下限）。"""
    fp = PA.verify()
    missing = [u for u in MANDATORY_PROTECTED_USERNAMES if u not in PA.PROTECTED_USERNAMES]
    if missing:
        raise TestSafetyViolation(
            "【A FAIL-CLOSED】保护名单缺失必备条目：" + ", ".join(missing)
        )
    if PA.TEST_DATABASE != MANDATORY_TEST_DATABASE:
        raise TestSafetyViolation(
            f"【D0 FAIL-CLOSED】测试库名被改写为 {PA.TEST_DATABASE!r}"
        )
    _S.checks.append(f"assets: fingerprint={fp[:16]} usernames={len(PA.PROTECTED_USERNAMES)}")
    return fp


# ── 判定核心（**纯函数**，便于自测）────────────────────────────────────
def evaluate_candidates(
    table: str,
    candidates: Sequence[Dict[str, Any]],
    wm: Optional[Dict[str, int]] = None,
    extra_created_ids: Optional[Iterable[int]] = None,
    protected_user_ids: Optional[Iterable[int]] = None,
    denylist_user_ids: Optional[Iterable[int]] = None,
) -> List[str]:
    """对「这条 DELETE 将要删除的候选行」逐行判定；返回违规原因列表（空 = 放行）。

    每一行都必须能**证明为本次会话新建**，且**不属于**任何受保护 / denylist 对象。
    任一条件不满足即产生一条违规原因 ⇒ 调用方 ABORT。
    """
    wm = _S.watermark if wm is None else wm
    extra = set(extra_created_ids or ())
    # ★ O-TBA-2（FAIL-CLOSED）：**缺键 = 水位线未知 ≠ 0**。
    #   旧实现 ``int(wm.get(table, 0))`` 把「取不到」与「空表(0)」混为一谈 ⇒
    #   判据 ``rid <= line_wm`` 对正常正整数主键**恒为 False** ⇒ C 层保护被静默跳过。
    #   0 只在**确实取到值**（该表当时为空）时才合法；取不到必须保持未知。
    _raw_wm = wm.get(table, None)
    if _raw_wm is None:
        wm_known, line_wm = False, None
    else:
        try:
            wm_known, line_wm = True, int(_raw_wm)
        except (TypeError, ValueError):
            wm_known, line_wm = False, None
    reasons: List[str] = []
    # ★ O-TBA-1（第二处）：身份集合由调用方按「(id, username) 配对」解析后传入
    #   （``resolve_live_identity_ids``）。**未传时回落静态名单** —— 纯函数调用方
    #   （自测）行为不变；引擎路径则只在「该身份在本库中确实存在」时才保护。
    prot_ids = set(PA.PROTECTED_USER_IDS if protected_user_ids is None else protected_user_ids)
    deny_ids = set(
        PA.PERMANENT_DENYLIST_USER_IDS if denylist_user_ids is None else denylist_user_ids
    )

    for row in candidates:
        rid = row.get("id")
        uname = row.get("username")
        uid = row.get("user_id")

        if rid is None:
            reasons.append(f"{table}: 候选行缺少 id ⇒ 无法证明为本次创建")
            continue

        rid = int(rid)

        # A 层：id / 用户名 denylist
        # ⚠️ O-TBA-1：``id`` 与用户身份同域**仅当** ``table in USER_IDENTITY_TABLES``
        #    （即 ``user_account``）。对子表，行自身 ``id`` 与该行「属于谁」无关，
        #    拿它比对 ``PROTECTED_USER_IDS`` / denylist 只会造成**假阳性否决**
        #    （实例：``health_record.id = 4833`` 被判为「受保护用户 4833」）。
        #    子表的保护语义由下方 ``user_id`` 外键段与 ``username`` 段承担 ——
        #    两者**均未改动**，保护能力零削弱。
        id_is_user_identity = table in USER_IDENTITY_TABLES
        if id_is_user_identity and rid in prot_ids:
            reasons.append(f"{table}#{rid}: 命中 PROTECTED_USER_IDS")
        if id_is_user_identity and rid in deny_ids:
            reasons.append(f"{table}#{rid}: 命中永久历史 denylist USER_IDS")
        if uname and str(uname) in PA.PROTECTED_USERNAMES:
            reasons.append(f"{table}#{rid}: 命中 PROTECTED_USERNAMES({uname})")
        if uname and str(uname) in PA.PERMANENT_DENYLIST_USERNAMES:
            reasons.append(f"{table}#{rid}: 命中永久历史 denylist({uname})")

        # A 层：目标行**属于**受保护 / denylist 账号
        if uid is not None:
            uid = int(uid)
            # ⚠️ 用**解析后**的身份集合：``user_id`` 数值本身不构成身份
            #    （实测 tst 账号会拿到 4833~4839 这些数字）。
            if uid in prot_ids:
                reasons.append(f"{table}#{rid}: 该行 user_id={uid} 属于受保护账号")
            if uid in deny_ids:
                reasons.append(f"{table}#{rid}: 该行 user_id={uid} 属永久 denylist")

        # C 层：必须证明为本次创建（显式登记 ∪ id 水位线以上）
        if rid in extra or rid in _S.created_ids:
            # 显式登记**独立于水位线**，是无歧义的创建证明 ⇒ 放行
            pass
        elif not wm_known:
            # ★ O-TBA-2：水位线不可得 ⇒ 无法证明「本会话创建」⇒ fail-closed 拒绝
            reasons.append(
                f"{table}#{rid}: 会话水位线不可用（{table} 未知），"
                "无法证明为本次会话创建 ⇒ fail-closed 拒绝"
            )
        elif rid <= line_wm:
            reasons.append(
                f"{table}#{rid}: 会删除**会话开始前已存在**的数据"
                f"（id <= 水位线 {line_wm}）"
            )

    return reasons


# ── A 层：静态 id 名单 → 「当前库中**真实存在**的身份」──────────────────
def resolve_live_identity_ids(conn) -> Tuple[frozenset, frozenset]:
    """把静态 id 名单解析为**当前库中真实存在的身份**；返回 ``(受保护 ids, denylist ids)``。

    为什么必须解析（O-TBA-1 第二处 · 实测）
    --------------------------------------
    ``PROTECTED_USER_IDS`` 是 **开发库** 2026-09-24 的实测值（4833/4834/4836/4838），
    而守卫只在 **D0 专用测试库** 上运行 —— 两者是**两套互不相干的自增 id 空间**。
    实测：一次**合并全量会话**创建 234 个测试账号，id 从 4659 漂移到 4902，其中
    **6 个普通测试账号**恰好拿到 4833/4834/4836/4837/4838/4839，用户名却是
    ``tst159402`` / ``tstpb7bc25`` / ``tstnullemail5ac083`` …… ⇒
    裸数字比对把它们误判为 ``top001``/``top002``/``tst35ro1`` ⇒ 这些 tst 账号的
    **全部**清理被 fail-closed 拒绝 ⇒ 级联 370 errors。

    **裸数字不是身份，``(id, username)`` 配对才是。** 故只有「该 id 在本库中**确实**
    以受保护 / denylist 用户名存在」时才计入保护集合。

    安全性（**不是放宽**）
    ----------------------
    * 返回集合恒为静态名单的**子集**（不新增、不臆造）；
    * 本库确实存在受保护账号时（如以开发库快照种入）⇒ 解析命中 ⇒ 保护照旧生效，
      且**比原来更准**（按身份而非序号）；
    * ``username`` 层的保护（``PROTECTED_USERNAMES`` / denylist）**完全不依赖**本函数，
      始终生效；
    * 解析异常 ⇒ **回落静态名单**（fail-closed：宁可更严，绝不放松）。

    不缓存：会话中账号会被创建 / 删除，缓存会掩盖「刚出现的受保护账号」⇒ fail-open。
    """
    static_prot = frozenset(int(i) for i in PA.PROTECTED_USER_IDS)
    static_deny = frozenset(int(i) for i in PA.PERMANENT_DENYLIST_USER_IDS)
    wanted = sorted(static_prot | static_deny)
    if not wanted:
        return static_prot, static_deny
    try:
        # ``wanted`` 全部由本项目常量构造（纯 int），非外部输入 ⇒ 无注入面
        sql = "SELECT id, username FROM `user_account` WHERE id IN (%s)" % (
            ",".join(str(i) for i in wanted)
        )
        rows = conn.execute(text(sql)).fetchall()
    except Exception:  # noqa: BLE001 —— 解析失败 ⇒ 回落静态名单（fail-closed）
        return static_prot, static_deny
    live = {int(r[0]): str(r[1]) for r in rows}
    prot = frozenset(i for i in static_prot if live.get(i) in PA.PROTECTED_USERNAMES)
    deny = frozenset(i for i in static_deny if live.get(i) in PA.PERMANENT_DENYLIST_USERNAMES)
    return prot, deny


def _has_prefix_predicate(clauseelement) -> bool:
    """该 DELETE 是否含 ``LIKE`` 前缀谓词（仅用于**审计登记**，不参与放行判定）。"""
    try:
        crit = tuple(getattr(clauseelement, "_where_criteria", ()) or ())
    except Exception:  # noqa: BLE001
        return False
    for c in crit:
        if type(c).__name__ in ("BinaryExpression", "UnaryExpression"):
            op = getattr(c, "operator", None)
            oname = getattr(op, "__name__", type(op).__name__ if op is not None else "")
            if "like" in str(oname).lower():
                return True
    return False


def _caller_sites(limit: int = 6) -> List[str]:
    """采集**项目内**调用帧（``file:line``），用于把旧 cleanup 的位置钉死。

    过滤掉 ``testsafety`` 自身与 ``site-packages``（sqlalchemy 内部）——
    否则栈顶永远是库代码，看不到真正发起 DELETE 的那一行。
    """
    out: List[str] = []
    for f in traceback.extract_stack()[:-1]:
        fn = (f.filename or "").replace("/", "\\")
        low = fn.lower()
        # ⚠️ 必须按**路径段** ``\testsafety\`` 过滤，而不是子串 "testsafety"——
        # 否则会把 `tests\test_testsafety_guard.py`（文件名里含 testsafety）也误滤掉。
        if "\\testsafety\\" in low or "site-packages" in low:
            continue
        out.append(f"{f.filename}:{f.lineno}")
    return out[-limit:]


def _veto(table: str, reason: str, clauseelement) -> "TestSafetyViolation":
    rec = {
        "session": _S.session_id,
        "table": table,
        "reason": reason,
        "statement": str(clauseelement)[:400],
        "created_ids": sorted(_S.created_ids)[:50],
        "watermark": _S.watermark.get(table),
        "site": _caller_sites(),
    }
    _S.vetoes.append(rec)
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with VETO_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return TestSafetyViolation(
        "【测试安全守卫 · ABORT】拒绝执行 DELETE（未执行，未删除任何行）：\n"
        f"  表      : {table}\n"
        f"  原因    : {reason}\n"
        f"  语句    : {str(clauseelement)[:200]}\n"
        "  说明：宁可留下测试残留，也绝不误删既有数据。"
    )


# ── 咽喉点：#1 物理建连时校验 DB（D0 最强形态）────────────────────────
def _on_connect(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cur = dbapi_connection.cursor()
    try:
        cur.execute("SELECT DATABASE()")
        row = cur.fetchone()
        db = "" if not row or row[0] is None else str(row[0]).strip()
    finally:
        cur.close()
    if db != TEST_DATABASE:
        raise TestSafetyViolation(
            "【D0 FAIL-CLOSED】建立物理连接时发现数据库不符：\n"
            f"  SELECT DATABASE() = {db!r}   必须 = {TEST_DATABASE!r}\n"
            f"  ⇒ pytest 下绝不允许连接 {DEV_DATABASE!r}。"
        )


# ── 文本 DELETE 的逐行预演（``text("DELETE FROM t WHERE ...")``）────────
#: 单表 ``DELETE FROM `t` [WHERE ...]`` —— 可改写成 ``SELECT * FROM ...`` 预演
_TEXT_DELETE_RE = re.compile(
    r"^\s*delete\s+from\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
#: ``TRUNCATE [TABLE] `t```（无 WHERE，必然清空 ⇒ 受管表一律否决）
_TEXT_TRUNCATE_RE = re.compile(
    r"^\s*truncate\s+(?:table\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?",
    re.IGNORECASE,
)
_TEXT_BIND_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _text_delete_plan(conn, clauseelement, params):
    """把 ``DELETE FROM t [WHERE ...]`` 改写成 ``SELECT * FROM t [WHERE ...]`` 做逐行预演。

    返回三元组 ``(tname, candidates, reason)``：

    * ``(None, None, None)``    ⇒ 与受管表无关，放行且**不干预**；
    * ``(tname, list, None)``   ⇒ 预演成功，交由 ``evaluate_candidates`` 判定；
    * ``(tname, None, reason)`` ⇒ **无法安全预演** ⇒ 调用方 ABORT（fail-closed）。
    """
    sql = str(clauseelement)
    m = _TEXT_DELETE_RE.match(sql)
    if not m:
        # 多表 DELETE（``DELETE t1 FROM t1 JOIN ...``）/ ``USING`` 等：涉及受管表即否决
        hit = [t for t in GUARDED_TABLES if re.search(r"\b%s\b" % re.escape(t), sql, re.I)]
        if hit:
            return (hit[0], None, "非单表 DELETE（无法逐行预演）；涉及受管表 " + ",".join(hit))
        return (None, None, None)

    tname, rest = m.group(1), m.group(2)
    if tname not in GUARDED_TABLES:
        return (None, None, None)
    if not rest.strip():
        return (tname, None, "无条件 DELETE（将清空整表）")

    sel_sql = "SELECT * FROM `%s` %s" % (tname, rest)
    use = {}
    if params:
        if not isinstance(params, dict):
            return (tname, None, "文本 DELETE 使用位置参数，无法逐行预演")
        for k in _TEXT_BIND_RE.findall(sel_sql):
            if k in params:
                use[k] = params[k]
    try:
        rows = conn.execute(text(sel_sql), use).fetchall()
    except Exception as ex:  # noqa: BLE001
        return (tname, None, "文本 DELETE 预演失败（fail-closed）：%s: %s" % (type(ex).__name__, ex))
    return (tname, [dict(r._mapping) for r in rows], None)


def _handle_text_delete(conn, clauseelement, params) -> None:
    """文本 DELETE / TRUNCATE 的统一处理入口（预演成功才放行）。"""
    low = str(clauseelement).strip().lower()
    if low.startswith("delete"):
        tname, cands, reason = _text_delete_plan(conn, clauseelement, params)
        if tname is None and cands is None and reason is None:
            return
        _S.deletes_seen += 1
        if cands is None:
            raise _veto(tname, reason, clauseelement)
        _lp, _ld = (resolve_live_identity_ids(conn) if cands
                    else (frozenset(), frozenset()))
        reasons = evaluate_candidates(tname, cands, protected_user_ids=_lp,
                                      denylist_user_ids=_ld)
        if reasons:
            raise _veto(tname, "；".join(reasons[:6]), clauseelement)
        _S.deletes_allowed += 1
        return
    if low.startswith("truncate"):
        m = _TEXT_TRUNCATE_RE.match(str(clauseelement))
        if m and m.group(1) in GUARDED_TABLES:
            raise _veto(m.group(1), "TRUNCATE 受管表（将清空整表）", clauseelement)


# ── 咽喉点：#2 每条 DELETE 的删除前预演（C + A）────────────────────────
def _on_before_execute(conn, clauseelement, multiparams, params, execution_options):  # noqa: ANN001
    if not _S.installed:
        return
    if not _S.watermark_taken and conn.engine is not None:
        try:
            capture_watermark(conn)
        except Exception as ex:  # noqa: BLE001
            # ★ O-TBA-2（FAIL-CLOSED）：取线失败**绝不**降级为「无水位线 = 放行」。
            #   保持 ``_S.watermark`` 为空 ⇒ C 层对受管表一律拒绝（响亮失败）。
            _S.watermark_failed = {"<lazy-capture>": f"{type(ex).__name__}: {ex}"}
        finally:
            # 只尝试一次，避免每条 DELETE 都重试；fail-closed 由「未知水位线」承载。
            _S.watermark_taken = True

    # 文本 DELETE / TRUNCATE：**尽量**逐行预演；无法预演 ⇒ 否决（fail-closed）
    if isinstance(clauseelement, TextClause):
        _handle_text_delete(conn, clauseelement, params)
        return

    if not isinstance(clauseelement, Delete):
        return

    tbl = getattr(clauseelement, "table", None)
    tname = getattr(tbl, "name", None)
    if tname not in GUARDED_TABLES:
        return

    _S.deletes_seen += 1
    crit = tuple(getattr(clauseelement, "_where_criteria", ()) or ())
    if not crit:
        raise _veto(tname, "无条件 DELETE（将清空整表）", clauseelement)

    if _has_prefix_predicate(clauseelement):
        _S.prefix_only_seen.append(
            {
                "table": tname,
                "statement": str(clauseelement)[:200],
                "allowed": None,
                "site": _caller_sites(4),
            }
        )

    try:
        cols = ["id"] if "id" in tbl.columns.keys() else []
        if "username" in tbl.columns.keys():
            cols.append("username")
        if "user_id" in tbl.columns.keys():
            cols.append("user_id")
        if not cols:
            raise _veto(tname, "受管表缺少可审计列（id/username/user_id），无法预演", clauseelement)
        sel = select(*[tbl.c[c] for c in cols]).where(*crit)
        # ★ 阻塞 A 修复：ORM 删除预演**透传原始执行参数**。
        #   `session.delete(obj)` 在 flush 期生成的 DELETE 形如
        #   ``DELETE FROM `t` WHERE `t`.id = :id`` —— 其 WHERE 由**绑定参数**构成。
        #   旧实现只重建 ``SELECT ... WHERE <crit>`` 而不传参数 ⇒ 绑定参数无值
        #   ⇒ ``StatementError`` ⇒ fail-closed 否决（**预演能力缺口**，非产品缺陷）。
        #   现按「必须覆盖实际将删除的全部行」的原则转发参数：
        #     · 单组参数（``params``）⇒ 直接转发；
        #     · 多组参数（``multiparams`` = executemany）⇒ **逐组预演取并集**，
        #       绝不只取第一组（否则会漏行 ⇒ 放松安全性）；
        #     · 非映射参数 ⇒ 无法安全预演 ⇒ fail-closed 否决（不放松）。
        #   ★ 判据零改动：``evaluate_candidates`` / 水位线 / 保护名单 / denylist /
        #     fail-closed 全部原样；仅补齐「预演能否取到候选行」这一环。
        _param_sets: List[Dict[str, Any]] = []
        if multiparams:
            for _mp in multiparams:
                if isinstance(_mp, dict):
                    _param_sets.append(_mp)
                else:
                    raise _veto(
                        tname,
                        "删除前预演失败（fail-closed）：执行参数非映射类型 "
                        f"{type(_mp).__name__}",
                        clauseelement,
                    )
        elif isinstance(params, dict) and params:
            _param_sets.append(params)
        if not _param_sets:
            _param_sets = [{}]

        cands: List[Dict[str, Any]] = []
        _seen_keys: set = set()
        for _ps in _param_sets:
            for _r in conn.execute(sel, _ps).fetchall():
                _row = dict(zip(cols, _r))
                _k = tuple(_row.get(c) for c in cols)
                if _k not in _seen_keys:
                    _seen_keys.add(_k)
                    cands.append(_row)
    except TestSafetyViolation:
        raise
    except Exception as ex:  # noqa: BLE001
        raise _veto(tname, f"删除前预演失败（fail-closed）：{type(ex).__name__}: {ex}", clauseelement)

    # ★ O-TBA-1（第二处）：受保护身份按 (id, username) 配对解析后再判定
    _lp, _ld = (resolve_live_identity_ids(conn) if cands else (frozenset(), frozenset()))
    reasons = evaluate_candidates(tname, cands, protected_user_ids=_lp,
                                  denylist_user_ids=_ld)
    if reasons:
        if _S.prefix_only_seen and _S.prefix_only_seen[-1]["allowed"] is None:
            _S.prefix_only_seen[-1]["allowed"] = False
        raise _veto(tname, "；".join(reasons[:6]), clauseelement)

    if _S.prefix_only_seen and _S.prefix_only_seen[-1]["allowed"] is None:
        _S.prefix_only_seen[-1]["allowed"] = True
    _S.deletes_allowed += 1


def capture_watermark(conn) -> Dict[str, int]:
    """记录**会话开始前**每张受管表的 ``MAX(id)``（越晚越安全：须在任何写入之前）。"""
    wm: Dict[str, int] = {}
    failed: Dict[str, str] = {}
    for t in GUARDED_TABLES:
        try:
            wm[t] = int(conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM `{t}`")).scalar() or 0)
        except Exception as ex:  # noqa: BLE001
            # ★ O-TBA-2（FAIL-CLOSED）：**绝不**写 ``wm[t] = 0``。
            #   0 = 「取到了值：该表当时为空」；取不到 ⇒ 必须**缺键**（未知），
            #   由 ``evaluate_candidates`` 判为 fail-closed 拒绝。
            failed[t] = f"{type(ex).__name__}: {ex}"
    _S.watermark = wm
    _S.watermark_failed = failed
    _S.watermark_taken = True
    return wm


def capture_watermark_eager() -> Dict[str, int]:
    """在会话**最早期**（``pytest_configure``）用一条独立只读连接记录水位线。

    为什么必须「最早」：水位线 = 每张表的 ``MAX(id)``。越早取值，判据越保守——
    任何在它之后出现的行都算「本次新建」。若晚到某次测试写入之后才取值，
    那些本该被回收的行会被误判为「会话前已存在」⇒ 清理被否决（安全但会留下残留）。
    """
    from app.core.config import load_config

    uri = str(load_config()["SQLALCHEMY_DATABASE_URI"])
    eng = create_engine(uri, poolclass=pool.NullPool)
    try:
        with eng.connect() as conn:  # connect 事件会先校验 SELECT DATABASE()（D0）
            return capture_watermark(conn)
    finally:
        eng.dispose()


# ── 安装 ────────────────────────────────────────────────────────────────
def install() -> None:
    """安装两个引擎级咽喉点（进程内幂等）。"""
    if _S.installed:
        return
    event.listen(Engine, "connect", _on_connect)
    event.listen(Engine, "before_execute", _on_before_execute)
    _S.installed = True
    _S.checks.append("installed: Engine.connect + Engine.before_execute")


# ── 审计 ────────────────────────────────────────────────────────────────
def audit() -> Dict[str, Any]:
    return {
        "session": _S.session_id,
        "installed": _S.installed,
        "test_database": TEST_DATABASE,
        "dev_database": DEV_DATABASE,
        "guarded_tables": list(GUARDED_TABLES),
        "watermark_taken": _S.watermark_taken,
        "watermark": _S.watermark,
        "watermark_failed": _S.watermark_failed,
        "deletes_seen": _S.deletes_seen,
        "deletes_allowed": _S.deletes_allowed,
        "vetoes": _S.vetoes,
        "prefix_predicates": _S.prefix_only_seen,
        "checks": _S.checks,
        "created_ids": sorted(_S.created_ids),
        "created_usernames": sorted(_S.created_usernames),
        "assets_fingerprint": PA.fingerprint(),
    }


def dump_audit(path: Optional[Path] = None) -> Path:
    p = Path(path) if path else AUDIT_JSON
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(audit(), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return p
