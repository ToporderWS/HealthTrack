# -*- coding: utf-8 -*-
"""B1-R-FIX · 测试安全守卫的**自测**（不写任何业务数据）。

覆盖策略（诚实标注）
--------------------
======================  ==========================================================
**纯函数单测**            ``guard.evaluate_candidates`` 的 C / A 判定——用**合成候选行**
                          验证「已存在行」「受保护 id/用户名」「denylist」均被否决。
                          不依赖库里是否有数据，因此**无需造数据**。
**引擎级端到端**          「无条件 DELETE」「文本 DELETE」两条**必然越界**的语句，
                          真实提交给引擎，断言被守卫**在真正执行前**抛错拦截。
                          （若守卫失效，最坏后果仅限**专用测试库**——D0 已把开发库
                          排除在外；绝不触碰开发库。）
**D0 实连校验**           ``SELECT DATABASE()`` 必须 = 专用测试库；应用 URI 亦须指向它。
**静态纪律**              ① ``app/**`` 不得 import ``testsafety``（S3 要求 2）；
                          ② ``testsafety/**`` 自身不得出现 LIKE 前缀删除模式。
======================  ==========================================================
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, text

from app.models.user_account import UserAccount
from testsafety import guard
from testsafety import protected_assets as PA

BACKEND = Path(__file__).resolve().parents[1]


# ── A 层：名单完整性 ────────────────────────────────────────────────────
def test_protected_assets_fingerprint_frozen():
    fp = PA.verify()
    assert fp == PA.EXPECTED_FINGERPRINT
    assert len(fp) == 64


def test_mandatory_protected_members_present():
    for u in guard.MANDATORY_PROTECTED_USERNAMES:
        assert u in PA.PROTECTED_USERNAMES, f"保护名单缺失必备账号：{u}"
    assert len(PA.PROTECTED_USERNAMES) == len(PA.PROTECTED_USER_IDS)


def test_protected_and_denylist_are_disjoint():
    """已误删账号**不得**被写成「仍存在的保护对象」（S4）。"""
    assert not (set(PA.PROTECTED_USERNAMES) & set(PA.PERMANENT_DENYLIST_USERNAMES))
    assert not (set(PA.PROTECTED_USER_IDS) & set(PA.PERMANENT_DENYLIST_USER_IDS))


# ── D0：库名钉死与 fail-closed ─────────────────────────────────────────
def test_force_test_database_pins_env():
    fake: dict = {"MYSQL_DB": PA.DEV_DATABASE}
    assert guard.force_test_database(fake) == PA.TEST_DATABASE
    assert fake["MYSQL_DB"] == PA.TEST_DATABASE


def test_preflight_accepts_test_db():
    assert guard.preflight_check({"MYSQL_DB": PA.TEST_DATABASE}) == PA.TEST_DATABASE


def test_preflight_rejects_dev_db_fail_closed():
    with pytest.raises(guard.TestSafetyViolation):
        guard.preflight_check({"MYSQL_DB": PA.DEV_DATABASE})


def test_preflight_rejects_missing_db_fail_closed():
    with pytest.raises(guard.TestSafetyViolation):
        guard.preflight_check({})


def test_root_conftest_installed_guard():
    assert guard._S.installed is True


def test_connected_database_is_dedicated_test_db(app):  # noqa: ANN001
    from app.core.db import get_engine

    with get_engine().connect() as conn:
        assert guard.assert_on_test_database(conn) == PA.TEST_DATABASE


def test_app_uri_points_at_test_db(app):  # noqa: ANN001
    uri = str(app.config["SQLALCHEMY_DATABASE_URI"])
    db = uri.rsplit("/", 1)[-1].split("?", 1)[0]
    # ⚠️ 只断言库名；**不打印 URI**（含凭据）
    assert db == PA.TEST_DATABASE, f"应用连接的不是专用测试库（实际库名 = {db!r}）"


# ── C / A 层：判定核心（纯函数） ───────────────────────────────────────
def _wm_high(table="user_account"):
    return {t: 0 for t in guard.GUARDED_TABLES} | {table: 1000}


def test_evaluate_allows_rows_created_this_session():
    cands = [{"id": 1001, "username": "tstabcd12", "user_id": None}]
    assert guard.evaluate_candidates("user_account", cands, wm=_wm_high()) == []


def test_evaluate_vetoes_pre_existing_row():
    """水位线之下的行 = 会话开始前已存在 ⇒ 必须 ABORT（B1 事故的直接成因）。"""
    cands = [{"id": 999, "username": "tstabcd12", "user_id": None}]
    reasons = guard.evaluate_candidates("user_account", cands, wm=_wm_high())
    assert reasons and "会话开始前已存在" in reasons[0]


def test_evaluate_vetoes_protected_username():
    cands = [{"id": 5001, "username": "top001", "user_id": None}]
    reasons = guard.evaluate_candidates("user_account", cands, wm=_wm_high())
    assert any("PROTECTED_USERNAMES" in r for r in reasons)


def test_evaluate_vetoes_protected_id():
    cands = [{"id": PA.PROTECTED_USER_IDS[0], "username": "whatever", "user_id": None}]
    reasons = guard.evaluate_candidates("user_account", cands, wm=_wm_high())
    assert any("PROTECTED_USER_IDS" in r for r in reasons)


def test_evaluate_vetoes_denylist_username():
    """已误删账号名进入永久 denylist ⇒ 同名对象此后不得被自动删除。"""
    for name in PA.PERMANENT_DENYLIST_USERNAMES:
        cands = [{"id": 7001, "username": name, "user_id": None}]
        reasons = guard.evaluate_candidates("user_account", cands, wm=_wm_high())
        assert any("denylist" in r for r in reasons), name


def test_evaluate_vetoes_denylist_id():
    for rid in PA.PERMANENT_DENYLIST_USER_IDS:
        cands = [{"id": rid, "username": "tstwhatever", "user_id": None}]
        reasons = guard.evaluate_candidates("user_account", cands, wm=_wm_high())
        assert any("denylist" in r for r in reasons), rid


def test_evaluate_vetoes_row_owned_by_protected_account():
    """会话中新建的**行**若属于受保护账号（如 top001 的新 session）⇒ 也必须 ABORT。"""
    cands = [{"id": 8001, "user_id": PA.PROTECTED_USER_IDS[1]}]
    reasons = guard.evaluate_candidates("user_session", cands, wm=_wm_high("user_session"))
    assert any("属于受保护账号" in r for r in reasons)


def test_evaluate_vetoes_row_without_id():
    reasons = guard.evaluate_candidates("user_profile", [{"id": None}], wm=_wm_high("user_profile"))
    assert reasons and "无法证明为本次创建" in reasons[0]


def test_evaluate_empty_candidates_is_noop():
    assert guard.evaluate_candidates("user_account", [], wm=_wm_high()) == []


# ── O-TBA-1：表语义 —— 「行自身 id」只有对 user_account 才是用户身份 ──────
#: **表语义矩阵**（本批新增判据的机读形式）：
#: ・``user_account``：主键 ``id`` **就是**用户身份 ⇒ 可与 ``PROTECTED_USER_IDS`` /
#:   ``PERMANENT_DENYLIST_USER_IDS`` 比对；本表**无** ``user_id`` 列。
#: ・下列 8 张表：``id`` 为各自独立自增主键，与 ``user_account.id`` **无任何语义关联**
#:   （V1.0 表间 0 外键）⇒ 保护语义只能经 **``user_id`` 外键** 表达。
#: ・``login_failure_state``：既无 ``user_id`` 列、``id`` 亦非用户身份 ⇒
#:   保护语义只能经 **``username``** 表达（该账号防枚举，故按用户名落行）。
TABLES_WHERE_ID_IS_USER_IDENTITY = ("user_account",)
TABLES_PROTECTED_VIA_FK = (
    "user_profile", "health_record", "record_tag", "health_goal",
    "user_session", "export_job", "verification_code", "password_reset_token",
)
TABLES_PROTECTED_VIA_USERNAME_ONLY = ("login_failure_state",)


def test_table_semantics_matrix_covers_all_tables():
    """矩阵必须**恰好覆盖** V1.0 全部 10 张表（无遗漏、无重复）。"""
    from app.models import ALL_TABLES

    covered = (
        set(TABLES_WHERE_ID_IS_USER_IDENTITY)
        | set(TABLES_PROTECTED_VIA_FK)
        | set(TABLES_PROTECTED_VIA_USERNAME_ONLY)
    )
    assert covered == set(ALL_TABLES)
    assert len(TABLES_WHERE_ID_IS_USER_IDENTITY) == 1
    # 矩阵与模型层事实一致：只有 user_account 的 id 是用户身份
    from app.models.user_profile import UserProfile
    from app.models.user_account import UserAccount

    assert "user_id" not in UserAccount.__table__.columns.keys()
    assert "user_id" in UserProfile.__table__.columns.keys()
    from app.models.login_failure_state import LoginFailureState

    assert "user_id" not in LoginFailureState.__table__.columns.keys()


@pytest.mark.parametrize("rid", PA.PROTECTED_USER_IDS)
def test_child_table_own_id_is_not_protected_user_id(rid):  # noqa: ANN001
    """★ O-TBA-1 复现：``health_record.id == 4833`` 与「受保护用户 4833」**无关**。

    该行 ``user_id=3896`` 不属任何受保护账号 ⇒ 不得产生任何否决理由。
    （修复前：误报 ``health_record#4833: 命中 PROTECTED_USER_IDS``，进而否决整条
    DELETE ⇒ 会话内清理被拒 ⇒ 记录行滞留为孤儿 ⇒ 下一会话又被水位线否决。）
    """
    cands = [{"id": rid, "user_id": 3896}]
    reasons = guard.evaluate_candidates("health_record", cands, wm=_wm_high("health_record"))
    assert reasons == [], f"子表行自身 id={rid} 被误判为受保护用户 id：{reasons}"


@pytest.mark.parametrize("rid", PA.PERMANENT_DENYLIST_USER_IDS)
def test_child_table_own_id_is_not_denylist_user_id(rid):  # noqa: ANN001
    """同上的 denylist 变体（``record_tag`` 自增序列紧邻 4837/4839/4840）。"""
    cands = [{"id": rid, "user_id": 3896}]
    reasons = guard.evaluate_candidates("record_tag", cands, wm=_wm_high("record_tag"))
    assert reasons == [], f"子表行自身 id={rid} 被误判为 denylist 用户 id：{reasons}"


def test_login_failure_state_own_id_is_not_user_id():
    """``login_failure_state`` 无 ``user_id`` 列 ⇒ 行自身 id 同样不得参与用户 id 比对。"""
    cands = [{"id": PA.PROTECTED_USER_IDS[0], "username": "tstabcd12", "user_id": None}]
    reasons = guard.evaluate_candidates(
        "login_failure_state", cands, wm=_wm_high("login_failure_state")
    )
    assert reasons == []


def test_user_account_own_id_is_still_protected_id():
    """★ 回归（能力不得回流）：``user_account`` 自身 id 仍是**唯一** id 语义层。"""
    for rid in PA.PROTECTED_USER_IDS:
        reasons = guard.evaluate_candidates(
            "user_account", [{"id": rid, "username": "whatever", "user_id": None}],
            wm=_wm_high(),
        )
        assert any("PROTECTED_USER_IDS" in r for r in reasons), rid
    for rid in PA.PERMANENT_DENYLIST_USER_IDS:
        reasons = guard.evaluate_candidates(
            "user_account", [{"id": rid, "username": "whatever", "user_id": None}],
            wm=_wm_high(),
        )
        assert any("denylist" in r for r in reasons), rid


def test_child_table_protection_still_flows_through_user_id():
    """★ 回归：子表保护**未削弱** —— 行 ``user_id`` 命中受保护 / denylist 仍否决。"""
    for rid in PA.PROTECTED_USER_IDS:
        reasons = guard.evaluate_candidates(
            "health_record", [{"id": 9001, "user_id": rid}], wm=_wm_high("health_record")
        )
        assert any("属于受保护账号" in r for r in reasons), rid
    for rid in PA.PERMANENT_DENYLIST_USER_IDS:
        reasons = guard.evaluate_candidates(
            "record_tag", [{"id": 9002, "user_id": rid}], wm=_wm_high("record_tag")
        )
        assert any("denylist" in r for r in reasons), rid


def test_login_failure_state_protection_still_flows_through_username():
    """★ 回归：``login_failure_state`` 按 username 的保护**未削弱**。"""
    for name in PA.PROTECTED_USERNAMES:
        reasons = guard.evaluate_candidates(
            "login_failure_state", [{"id": 9003, "username": name, "user_id": None}],
            wm=_wm_high("login_failure_state"),
        )
        assert any("PROTECTED_USERNAMES" in r for r in reasons), name
    for name in PA.PERMANENT_DENYLIST_USERNAMES:
        reasons = guard.evaluate_candidates(
            "login_failure_state", [{"id": 9004, "username": name, "user_id": None}],
            wm=_wm_high("login_failure_state"),
        )
        assert any("denylist" in r for r in reasons), name


def test_child_table_watermark_still_enforced():
    """★ 回归：C 层（水位线）对子表**未削弱** —— 会话前已存在的行仍 ABORT。"""
    cands = [{"id": 10, "user_id": 9005}]
    reasons = guard.evaluate_candidates("health_record", cands, wm=_wm_high("health_record"))
    assert reasons and "会话开始前已存在" in reasons[0]


# ── O-TBA-1（第二处）：保护身份必须按「(id, username) 配对」解析，而非裸数字 ──
#: 实测事实（本批只读探针）：一次**合并全量会话**创建 234 个测试账号，id 从 4659
#: 漂移到 4902，其中 **6 个普通测试账号**恰好拿到 4833/4834/4836/4837/4838/4839
#: （即受保护 / denylist 名单里的数字），用户名却是 ``tst159402`` / ``tstpb7bc25`` ……
#: ``PROTECTED_USER_IDS`` 是**开发库**实测值，而守卫只运行在 **D0 专用测试库** ——
#: 两套**互不相干**的自增 id 空间。裸数字不是身份，``(id, username)`` 配对才是。
def test_fk_numeric_collision_is_not_a_protected_account():
    """★ 复现：测试账号 tstpb7bc25(id=4834) 的行，不得被判为「受保护账号 top002 的行」。"""
    cands = [{"id": 1546, "user_id": 4834}]
    reasons = guard.evaluate_candidates(
        "health_goal", cands, wm=_wm_high("health_goal"),
        protected_user_ids=frozenset(), denylist_user_ids=frozenset(),
    )
    assert reasons == [], f"tst 账号被误判为受保护账号：{reasons}"


def test_fk_collision_still_vetoed_when_protected_identity_is_live():
    """★ 回归：当该库中**确实**存在受保护账号（id 与用户名配对）时，保护照旧生效。"""
    cands = [{"id": 1546, "user_id": 4834}]
    reasons = guard.evaluate_candidates(
        "health_goal", cands, wm=_wm_high("health_goal"),
        protected_user_ids=frozenset({4834}), denylist_user_ids=frozenset(),
    )
    assert any("属于受保护账号" in r for r in reasons)


def test_fk_denylist_collision_is_not_denylist_identity():
    """denylist 同族：tstnullemail5ac083(id=4837) 不是已删的 ``tst35ro1``。"""
    cands = [{"id": 9001, "user_id": 4837}]
    reasons = guard.evaluate_candidates(
        "user_session", cands, wm=_wm_high("user_session"),
        protected_user_ids=frozenset(), denylist_user_ids=frozenset(),
    )
    assert reasons == []


def test_evaluate_defaults_to_static_lists_for_callers_without_resolution():
    """★ 兼容性：不传解析结果时，仍按**静态名单**判定（纯函数调用方的既有行为不变）。"""
    cands = [{"id": 1546, "user_id": PA.PROTECTED_USER_IDS[1]}]
    reasons = guard.evaluate_candidates("health_goal", cands, wm=_wm_high("health_goal"))
    assert any("属于受保护账号" in r for r in reasons)


def test_resolve_live_identity_ids_are_pair_verified(app):  # noqa: ANN001
    """解析结果必须是**配对着地核验过**的子集（不新增、不臆造）。"""
    from app.core.db import get_engine

    with get_engine().connect() as conn:
        prot, deny = guard.resolve_live_identity_ids(conn)
    assert set(prot) <= set(PA.PROTECTED_USER_IDS)
    assert set(deny) <= set(PA.PERMANENT_DENYLIST_USER_IDS)

    from sqlalchemy import text as _t

    with get_engine().connect() as conn:
        for rid in prot:
            got = conn.execute(_t("SELECT username FROM user_account WHERE id=:i"),
                               {"i": int(rid)}).scalar()
            assert got in PA.PROTECTED_USERNAMES, (rid, got)
        for rid in deny:
            got = conn.execute(_t("SELECT username FROM user_account WHERE id=:i"),
                               {"i": int(rid)}).scalar()
            assert got in PA.PERMANENT_DENYLIST_USERNAMES, (rid, got)


def test_resolve_live_identity_ids_fail_closed_on_error():
    """解析异常 ⇒ 回落到**静态名单**（fail-closed：宁可更严，绝不放松）。"""

    class _Bad:
        def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    prot, deny = guard.resolve_live_identity_ids(_Bad())
    assert set(prot) == set(PA.PROTECTED_USER_IDS)
    assert set(deny) == set(PA.PERMANENT_DENYLIST_USER_IDS)


def test_engine_fk_numeric_collision_row_can_be_cleaned(app):  # noqa: ANN001
    """★ 端到端：``user_id`` 数值命中受保护区间的**本会话新建**行必须可被清理。

    该库中并不存在受保护账号 ⇒ 数值无身份含义 ⇒ 修复后应放行（修复前被否决）。
    """
    from datetime import date, datetime

    from sqlalchemy import delete as sa_delete, func, select

    from app.core.db import get_engine, get_session_factory
    from app.models.health_goal import HealthGoal

    # 行 id 显式取「当前 MAX(id) + 1000」⇒ **必然高于会话水位线**，
    # 使 C 层（水位线）不介入，把断言精确钉在 A 层的**身份判定**上。
    with get_session_factory()() as db:
        top = int(db.execute(
            select(func.coalesce(func.max(HealthGoal.id), 0))
        ).scalar() or 0)
    gid = top + 1000

    now = datetime.now()
    with get_session_factory()() as db:
        db.add(HealthGoal(
            # ``deleted_marker=gid`` 保证命中 `uk_goal_user_type_active`
            # （=(user_id, goal_type, deleted_marker)）的唯一性，避免与库中
            # 既有行冲突（该行在用例结束前会被删除）。
            id=gid, user_id=int(PA.PROTECTED_USER_IDS[1]), goal_type="sleep",
            period_type="daily", target_value=2000, unit="ml", attr_1=None,
            start_weight_kg=None, start_date=date.today(), target_date=None,
            status=1, is_deleted=0, deleted_at=None, deleted_marker=gid,
            created_at=now, updated_at=now,
        ))
        db.commit()

    try:
        with get_engine().begin() as conn:
            conn.execute(sa_delete(HealthGoal).where(HealthGoal.id == gid))
        with get_session_factory()() as db:
            assert db.execute(
                sa_delete(HealthGoal).where(HealthGoal.id == gid)
            ).rowcount == 0, "该行本应已被删除（A 层身份判定已按 (id, username) 解析）"
            db.commit()
    finally:
        with get_session_factory()() as db:
            db.execute(sa_delete(HealthGoal).where(HealthGoal.id == gid))
            db.commit()


# ── 引擎级端到端：必然越界的两条语句必须被**执行前**拦截 ────────────────
def test_engine_vetoes_unconditional_delete(app):  # noqa: ANN001
    """无条件 DELETE（清空整表）——守卫必须在执行前抛错。

    若守卫失效，最坏后果仅限**专用测试库**的 user_account；
    开发库由 D0（连接期 SELECT DATABASE() 断言）排除在外。
    """
    from app.core.db import get_engine

    with pytest.raises(guard.TestSafetyViolation):
        with get_engine().begin() as conn:
            conn.execute(delete(UserAccount))


def test_engine_vetoes_text_delete_on_guarded_table(app):  # noqa: ANN001
    from app.core.db import get_engine

    with pytest.raises(guard.TestSafetyViolation):
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM user_account"))


def test_engine_allows_delete_with_no_matching_rows(app):  # noqa: ANN001
    """正当删除（候选为空）不被误拦：守卫只否决**有风险**的删除。"""
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(delete(UserAccount).where(UserAccount.id == -1))


# ── 静态纪律 ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════
# ★ O-TBA-2 · Watermark FAIL-CLOSED（水位线**不可得** ⇒ 拒绝删除）
# ══════════════════════════════════════════════════════════════════════
# 【旧行为（fail-open）· 观察记录】
#   ① ``capture_watermark`` 逐表取 ``MAX(id)`` 失败时写 ``wm[t] = 0``；
#   ② ``evaluate_candidates`` 用 ``int(wm.get(table, 0))`` 取线 —— **缺键同样是 0**；
#   ③ C 层判据是 ``rid <= line_wm`` —— 对**正常正整数主键恒为 False**。
#   ⇒ 「水位线取不到」被静默等同为「空表(0)」⇒ **C 层保护被整体跳过**（fail-open）。
#
# 【新行为（fail-closed）】
#   **缺键 = 水位线未知 ≠ 0**。未知 ⇒ C 层拒绝；除非该行另有**独立于水位线**的
#   证明（``_S.created_ids`` / 调用方显式传入的 ``extra_created_ids``）。
#   原则：**无法证明删除安全 ⇒ 拒绝删除**。
#
# 【为什么 ``wm[t] == 0`` 仍要放行】0 是**取到了值**（该表当时为空），不是「取不到」——
#   两者必须区分，否则回归时会误伤真实空表场景。
O_TBA2_REASON_KEY = "会话水位线"


def _wm_unknown_for(table, known=1000):
    """全部受管表水位线已知（= ``known``），但 ``table`` **缺键** ⇒ 该表水位线未知。"""
    wm = {t: known for t in guard.GUARDED_TABLES}
    wm.pop(table, None)
    return wm


def _o_tba2_snapshot():
    return (dict(guard._S.watermark), bool(guard._S.watermark_taken))


def _o_tba2_restore(snap):
    guard._S.watermark, guard._S.watermark_taken = dict(snap[0]), snap[1]


# ── CASE 1：水位线正常取得 ⇒ 现有合法删除行为**逐字不变** ────────────────
def test_o_tba2_case1_normal_watermark_behaviour_unchanged():
    """CASE 1：本会话新建行放行；会话开始前已存在的行照旧 ABORT。"""
    ok = [{"id": 1001, "username": "tstabcd12", "user_id": None}]
    assert guard.evaluate_candidates("user_account", ok, wm=_wm_high()) == []
    old = [{"id": 999, "username": "tstabcd12", "user_id": None}]
    reasons = guard.evaluate_candidates("user_account", old, wm=_wm_high())
    assert reasons and "会话开始前已存在" in reasons[0]


def test_o_tba2_case1_watermark_zero_is_known_empty_table_not_unknown():
    """**关键区分**：``wm[t] == 0`` 是「已知空表」，**不是**「未知」⇒ 必须照常放行。"""
    wm = {t: 0 for t in guard.GUARDED_TABLES}
    cands = [{"id": 1, "username": "tstabcd12", "user_id": None}]
    assert guard.evaluate_candidates("user_account", cands, wm=wm) == []


# ── CASE 3：水位线缺失 ⇒ 即使完全无害的行也必须 fail-closed ──────────────
def test_o_tba2_case3_unknown_watermark_vetoes_harmless_row():
    """CASE 3：非 protected id / 非 denylist / 用户名不受保护 —— 仍必须拒绝。"""
    cands = [{"id": 1001, "username": "tstabcd12", "user_id": None}]
    reasons = guard.evaluate_candidates(
        "user_account", cands, wm=_wm_unknown_for("user_account")
    )
    assert reasons, "水位线未知时不得放行"
    assert any(O_TBA2_REASON_KEY in r for r in reasons), reasons
    # 该否决**只能**来自 C 层（水位线不可证），不得是 A 层误报
    assert not any("PROTECTED" in r or "denylist" in r for r in reasons), reasons


@pytest.mark.parametrize("table", guard.GUARDED_TABLES)
def test_o_tba2_case3b_unknown_watermark_vetoes_every_guarded_table(table):
    """CASE 3（全表）：任何受管表只要水位线未知，一律拒绝。"""
    reasons = guard.evaluate_candidates(table, [{"id": 1001}], wm=_wm_unknown_for(table))
    assert reasons and any(O_TBA2_REASON_KEY in r for r in reasons), (table, reasons)


def test_o_tba2_empty_watermark_dict_is_unknown():
    """整个水位线字典为空（从未取线）⇒ 该表水位线未知 ⇒ 拒删。"""
    reasons = guard.evaluate_candidates(
        "user_account", [{"id": 1001, "username": "tstx", "user_id": None}], wm={}
    )
    assert reasons and any(O_TBA2_REASON_KEY in r for r in reasons)


# ── CASE 4：水位线恢复 ⇒ 本会话合法新建数据仍可正常清理 ─────────────────
def test_o_tba2_case4_restored_watermark_restores_cleanup():
    """CASE 4（纯函数）：未知 ⇒ 拒；恢复 ⇒ 放行。"""
    cands = [{"id": 1001, "username": "tstabcd12", "user_id": None}]
    assert guard.evaluate_candidates(
        "user_account", cands, wm=_wm_unknown_for("user_account")
    )
    assert guard.evaluate_candidates("user_account", cands, wm=_wm_high()) == []


def test_o_tba2_case4_engine_cleanup_ok_with_normal_watermark(app):  # noqa: ANN001
    """CASE 4（端到端）：水位线正常 ⇒ 本会话新建的受管行可被正常清理（零行为漂移）。"""
    from datetime import datetime

    from sqlalchemy import delete as sa_delete, func, select

    from app.core.db import get_session_factory
    from app.models.login_failure_state import LoginFailureState

    uname = "tstotba2case4"
    factory = get_session_factory()
    with factory() as db:
        db.execute(sa_delete(LoginFailureState).where(LoginFailureState.username == uname))
        db.commit()
    with factory() as db:
        db.add(LoginFailureState(
            username=uname, fail_count=0, first_fail_at=None, locked_until=None,
            lock_level=0, updated_at=datetime.now(),
        ))
        db.commit()
    with factory() as db:
        deleted = db.execute(
            sa_delete(LoginFailureState).where(LoginFailureState.username == uname)
        ).rowcount
        db.commit()
    assert deleted == 1, "水位线正常时，本会话新建行必须可正常清理（零行为漂移）"
    with factory() as db:
        left = int(db.execute(
            select(func.count()).select_from(LoginFailureState)
            .where(LoginFailureState.username == uname)
        ).scalar() or 0)
    assert left == 0


# ── CASE 5：A 层（protected / denylist / 身份配对）**全部保持** ──────────
def test_o_tba2_case5_protected_and_denylist_intact_when_watermark_unknown():
    """CASE 5：水位线未知**不得**削弱 A 层的任何一条保护。"""
    wm_acc = _wm_unknown_for("user_account")
    for rid in PA.PROTECTED_USER_IDS:
        r = guard.evaluate_candidates(
            "user_account", [{"id": rid, "username": "x", "user_id": None}], wm=wm_acc
        )
        assert any("PROTECTED_USER_IDS" in s for s in r), rid
    for rid in PA.PERMANENT_DENYLIST_USER_IDS:
        r = guard.evaluate_candidates(
            "user_account", [{"id": rid, "username": "x", "user_id": None}], wm=wm_acc
        )
        assert any("denylist" in s for s in r), rid
    wm_lfs = _wm_unknown_for("login_failure_state")
    for name in PA.PROTECTED_USERNAMES:
        r = guard.evaluate_candidates(
            "login_failure_state", [{"id": 9003, "username": name, "user_id": None}], wm=wm_lfs
        )
        assert any("PROTECTED_USERNAMES" in s for s in r), name
    for name in PA.PERMANENT_DENYLIST_USERNAMES:
        r = guard.evaluate_candidates(
            "login_failure_state", [{"id": 9004, "username": name, "user_id": None}], wm=wm_lfs
        )
        assert any("denylist" in s for s in r), name


def test_o_tba2_case5_identity_pairing_intact_when_watermark_unknown():
    """CASE 5：``(id, username)`` 配对语义（O-TBA-1）水位线未知时亦不变。"""
    wm = _wm_unknown_for("health_goal")
    live = guard.evaluate_candidates(
        "health_goal", [{"id": 1546, "user_id": 4834}], wm=wm,
        protected_user_ids=frozenset({4834}), denylist_user_ids=frozenset(),
    )
    assert any("属于受保护账号" in s for s in live)
    collision = guard.evaluate_candidates(
        "health_goal", [{"id": 1546, "user_id": 4834}], wm=wm,
        protected_user_ids=frozenset(), denylist_user_ids=frozenset(),
    )
    assert not any("属于受保护账号" in s for s in collision)


def test_o_tba2_explicit_registration_is_independent_of_watermark():
    """显式登记是**独立于水位线**的证明 —— 这不是 fail-open。

    引擎路径**从不**传 ``extra_created_ids``；``_S.created_ids`` 只由测试代码显式调用
    ``register_created_user()`` 填充（当前工程 **0 处调用**）。
    """
    cands = [{"id": 1001, "username": "tstx", "user_id": None}]
    wm = _wm_unknown_for("user_account")
    assert guard.evaluate_candidates("user_account", cands, wm=wm)
    assert guard.evaluate_candidates(
        "user_account", cands, wm=wm, extra_created_ids=[1001]
    ) == []


# ── ``capture_watermark`` 本体：取数失败**绝不**写 0 ────────────────────
class _Otba2FakeConn:
    """最小 Connection 替身：命中 ``fail_tables`` 的查询抛异常。"""

    def __init__(self, fail_tables=(), value=7):
        self.fail_tables = set(fail_tables)
        self.value = value

    def execute(self, stmt, *_a, **_k):  # noqa: ANN002, ANN003
        sql = str(stmt)
        for t in self.fail_tables:
            if "`%s`" % t in sql:
                raise RuntimeError("simulated MAX(id) failure: " + t)
        val = self.value

        class _R:
            def scalar(self):  # noqa: ANN201
                return val

        return _R()


def test_o_tba2_capture_watermark_never_defaults_to_zero_on_total_failure():
    """★ 核心判据：全部取数失败 ⇒ 返回**空字典**（未知），**绝不**写 0。"""
    snap = _o_tba2_snapshot()
    try:
        wm = guard.capture_watermark(_Otba2FakeConn(fail_tables=guard.GUARDED_TABLES))
        assert wm == {}, "取数失败时不得写入 0（0 会被当作「空表」而放行）：%r" % (wm,)
        assert all(t not in wm for t in guard.GUARDED_TABLES)
    finally:
        _o_tba2_restore(snap)


def test_o_tba2_capture_watermark_partial_failure_marks_only_failed_table_unknown():
    snap = _o_tba2_snapshot()
    try:
        wm = guard.capture_watermark(_Otba2FakeConn(fail_tables=("health_record",), value=7))
        assert "health_record" not in wm, "取不到的表明明失败却写了值"
        assert wm.get("user_account") == 7
        assert len(wm) == len(guard.GUARDED_TABLES) - 1
    finally:
        _o_tba2_restore(snap)


def test_o_tba2_capture_watermark_success_keeps_all_tables_known():
    snap = _o_tba2_snapshot()
    try:
        wm = guard.capture_watermark(_Otba2FakeConn(value=12345))
        assert set(wm) == set(guard.GUARDED_TABLES)
        assert set(wm.values()) == {12345}
    finally:
        _o_tba2_restore(snap)


# ── CASE 2：eager 失败 + 惰性获取同样失败 ⇒ **引擎级必须 ABORT** ─────────
def test_o_tba2_case2_engine_vetoes_delete_when_watermark_unavailable(app, monkeypatch):  # noqa: ANN001
    """CASE 2（端到端）：水位线取不到时，对受管表的 DELETE **不得执行**。"""
    from datetime import datetime

    from sqlalchemy import delete as sa_delete, func, select

    from app.core.db import get_engine, get_session_factory
    from app.models.login_failure_state import LoginFailureState

    uname = "tstotba2case2"
    factory = get_session_factory()

    def _cleanup() -> bool:
        with factory() as db:
            db.execute(sa_delete(LoginFailureState).where(LoginFailureState.username == uname))
            db.commit()
        with factory() as db:
            return int(db.execute(
                select(func.count()).select_from(LoginFailureState)
                .where(LoginFailureState.username == uname)
            ).scalar() or 0) == 0

    assert _cleanup(), "前置清理应成功（水位线正常）"
    with factory() as db:
        db.add(LoginFailureState(
            username=uname, fail_count=0, first_fail_at=None, locked_until=None,
            lock_level=0, updated_at=datetime.now(),
        ))
        db.commit()

    def _boom(*_a, **_k):  # noqa: ANN002, ANN003
        raise RuntimeError("simulated watermark capture failure (O-TBA-2 CASE 2)")

    snap = _o_tba2_snapshot()
    guard._S.watermark = {}          # ① eager 取线失败 ⇒ 无水位线
    guard._S.watermark_taken = False
    monkeypatch.setattr(guard, "capture_watermark", _boom)  # ② 惰性取线同样失败
    try:
        with pytest.raises(guard.TestSafetyViolation) as ei:
            with get_engine().begin() as conn:
                conn.execute(
                    sa_delete(LoginFailureState).where(LoginFailureState.username == uname)
                )
        assert O_TBA2_REASON_KEY in str(ei.value), str(ei.value)
        with factory() as db:
            left = int(db.execute(
                select(func.count()).select_from(LoginFailureState)
                .where(LoginFailureState.username == uname)
            ).scalar() or 0)
        assert left == 1, "守卫既已否决，行**必须**仍然存在（DELETE 不得继续执行）"
    finally:
        monkeypatch.undo()
        _o_tba2_restore(snap)

    assert _cleanup(), "水位线恢复后必须仍能正常清理（CASE 4 端到端）"


def test_product_code_does_not_import_testsafety():
    """S3 要求 2：产品代码不得依赖测试安全包。"""
    offenders = []
    for p in (BACKEND / "app").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "testsafety" in line:
                offenders.append(f"{p.relative_to(BACKEND)}:{i}")
    assert offenders == [], f"产品代码引用了 testsafety：{offenders}"


def test_testsafety_has_no_prefix_like_delete():
    """测试安全包自身**不得**出现 LIKE 前缀删除模式（前缀不得作为删除依据）。

    判据用 **AST** 而非子串匹配：``guard.py`` 的**文档字符串**里为说明「为什么
    前缀不能作依据」而引用了事故原句，那属于说明文字、不是代码。
    （铁律②：判据错 ⇒ 改判据，不改产品代码。）
    """
    import ast

    def _docstring_consts(tree):  # noqa: ANN001
        ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    ids.add(id(body[0].value))
        return ids

    offenders = []
    for p in (BACKEND / "testsafety").rglob("*.py"):
        src = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(BACKEND)
        tree = ast.parse(src, filename=str(p))
        docs = _docstring_consts(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("like", "ilike"):
                offenders.append(f"{rel}:{node.lineno}: .{node.attr}() 调用")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docs:
                    continue
                s = node.value.lower()
                if (" like " in s or ".like(" in s) and "delete" in s:
                    offenders.append(f"{rel}:{node.lineno}: 字符串同时含 DELETE 与 LIKE")
    assert offenders == [], f"testsafety 出现 LIKE 谓词：{offenders}"
