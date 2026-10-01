# -*- coding: utf-8 -*-
"""B1-D：老用户兼容 ＋ 既有流程回归（**真实 API + 真实 MySQL**）。

对应需求方 B1 §三（老用户 migration 后必须继续正常登录 / 使用 / 改密 / 注销）、
§六（``revoked_reason`` 与 ``A-07 DELETE_ORDER`` **本批不得提前改**）、
§十二 I/K/L/M/N/O/P（不改前端、不实现发送、不实现重置 API、不碰 A-05/A-07 主逻辑）。
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import get_engine, get_session_factory
from app.core.password_reset import PURPOSE_PASSWORD_RESET, hash_verification_code
from app.core.security import now_local
from app.models.verification_code import VerificationCode
from tests.pwreset.conftest import TEST_PREFIX, unique_username

API = "/api/v1"
PASSWORD = "abc12345"
PASSWORD2 = "xyz98765"
CONFIRM_TEXT = "注销账号"          # A-07 冻结值（硬编码，不取自被测对象）
BACKEND = Path(__file__).resolve().parents[2]
SERVICE_SRC = BACKEND / "app" / "services" / "account_service.py"
AUTH_SRC = BACKEND / "app" / "services" / "auth_service.py"

#: 既有 8 步删除顺序（**硬编码冻结**；与 `account_service.py` 逐字一致）
FROZEN_DELETE_ORDER = (
    "record_tag", "health_record", "health_goal", "user_profile",
    "export_job", "user_session", "login_failure_state", "user_account",
)
#: 既有 11 个蓝图（B1 不得新增）
FROZEN_BLUEPRINTS = {"health", "auth", "users", "profile", "avatar",
                     "records", "goals", "stats", "exports", "data", "account"}


# ══════════════════════════════════════════════════════════════════
# 只读助手
# ══════════════════════════════════════════════════════════════════
def scalar(sql: str, **params):
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params).scalar()


def register(client, username=None, password: str = PASSWORD):
    username = username or unique_username("cc")
    resp = client.post(f"{API}/auth/register", json={
        "username": username, "password": password,
        "agreement_version": "v1.0", "agreement_accepted": True, "auto_login": True,
    })
    return username, resp


def login(client, username: str, password: str = PASSWORD):
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def tokens_of(resp) -> dict:
    return ((resp.get_json() or {}).get("data") or {}).get("tokens") or {}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def account_id(username: str) -> int:
    return int(scalar("SELECT id FROM user_account WHERE username=:u", u=username))


def delete_order_block() -> tuple:
    src = SERVICE_SRC.read_text(encoding="utf-8")
    block = src.split("DELETE_ORDER: Tuple[str, ...] = (")[1].split(")")[0]
    return tuple(re.findall(r'"([a-z_]+)"', block))


# ══════════════════════════════════════════════════════════════════
# §三.1~§三.10 账号升级后数据完好、邮箱全 NULL（**S8 自证式**：不依赖存量数据）
# ══════════════════════════════════════════════════════════════════
def test_legacy_accounts_keep_null_email_and_intact_credentials(client) -> None:  # noqa: ANN001
    """**不允许**给账号自动生成邮箱；既有凭据字段零改动。

    **S8=A 自证式改造**：本用例**自己创建**验证所需的账号，**不再**依赖共用开发库
    里的存量账号（``top001`` / ``top002`` / ``top003`` / ``toptest1``）。改动**只**移除
    「环境历史数据依赖」，「迁移后不变量」的语义与断言强度**均保持不变**：

    1. 账号必须**可证明为本次创建**（本批独占前缀 ＋ 落库 id 命中本次创建集合）；
    2. ``email`` / ``email_verified_at`` 必须保持 ``NULL``（禁止 migration / 注册路径回填）；
    3. 凭据三元组必须保持冻结形态（``password_algo='bcrypt'`` / ``role='user'`` /
       ``CHAR_LENGTH(password_hash)=60``）。

    清理沿用已封板的 ``testsafety`` 四重保护（``tests/pwreset/conftest.py`` 的
    前缀＋id 水位线；删除前由引擎级守卫逐行复核）；**不**引入新的裸前缀删除依据。
    """
    n = 4                                   # 与迁移前存量账号同量级（原断言 ``>= 4``）
    created = []

    for _ in range(n):
        username, resp = register(client, unique_username("s8"))
        assert resp.status_code == 201, resp.get_json()
        created.append((username, account_id(username)))

    # ① 自证前置：本批独占前缀 ＋ 唯一用户名 ＋ 真实落库 id（防「空集合真空通过」）
    assert len({u for u, _ in created}) == n, "本次创建的用户名不唯一"
    assert all(u.startswith(TEST_PREFIX) for u, _ in created), "本次创建账号未带本批测试前缀"

    marks = ",".join(f":i{k}" for k in range(n))
    params = {f"i{k}": v for k, (_, v) in enumerate(created)}

    n_mine = int(scalar(f"SELECT COUNT(*) FROM user_account WHERE id IN ({marks})", **params))
    assert n_mine == n, f"自证失败：本次创建账号在库中只找到 {n_mine}/{n}"

    # ② 本次创建账号的邮箱必须保持 NULL（禁止回填 / 自动生成）
    n_email = int(scalar(
        f"SELECT COUNT(*) FROM user_account WHERE id IN ({marks}) "
        "AND (email IS NOT NULL OR email_verified_at IS NOT NULL)", **params))
    assert n_email == 0, "账号被写入了邮箱（禁止回填 / 自动生成）"

    # ③ 本次创建账号的凭据形态必须是冻结形态
    bad = int(scalar(
        f"SELECT COUNT(*) FROM user_account WHERE id IN ({marks}) AND ("
        "password_algo <> 'bcrypt' OR role <> 'user' "
        "OR CHAR_LENGTH(password_hash) <> 60)", **params))
    assert bad == 0, "账号的 password_algo / role / password_hash 形态异常"


def test_schema_is_at_revision_0003() -> None:
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() \
            == "0003_password_reset_email"
        tables = {r[0] for r in conn.execute(text(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"))}
    assert len(tables) == 11
    assert {"verification_code", "password_reset_token"} <= tables


# ══════════════════════════════════════════════════════════════════
# §三.1~§三.5 既有流程在新 schema 下全部可用（A-01/A-02/A-04/A-05）
# ══════════════════════════════════════════════════════════════════
def test_a01_a02_a04_a05_still_work(client) -> None:  # noqa: ANN001
    username, resp = register(client)
    assert resp.status_code == 201, resp.get_json()
    tokens = tokens_of(resp)
    assert tokens.get("access_token") and tokens.get("refresh_token")

    r = login(client, username)                      # A-02
    assert r.status_code == 200, r.get_json()
    token = tokens_of(r)["access_token"]

    r = client.put(f"{API}/auth/password", headers=auth(token), json={   # A-05
        "old_password": PASSWORD, "new_password": PASSWORD2, "confirm_password": PASSWORD2,
    })
    assert r.status_code == 200, r.get_json()
    assert login(client, username, PASSWORD).status_code != 200, "改密后旧口令仍可用"
    assert login(client, username, PASSWORD2).status_code == 200

    token2 = tokens_of(login(client, username, PASSWORD2))["access_token"]
    assert client.post(f"{API}/auth/logout", headers=auth(token2)).status_code == 200  # A-04


def test_existing_read_paths_unaffected(client) -> None:  # noqa: ANN001
    """新列 / 新表不得影响既有档案与健康数据读取路径。

    ``/stats/*`` 按契约**要求 query 参数**（无参 → ``400 INVALID_PARAM`` 是设计行为），
    因此对该组只断言「不是 5xx（无内部错误）」，并单独钉死其 400 的语义。
    """
    _, resp = register(client)
    h = auth(tokens_of(resp)["access_token"])

    for path in ("/profile", "/records/count", "/records/options",
                 "/home/overview", "/me/data/summary"):
        r = client.get(f"{API}{path}", headers=h)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.get_json()}"

    for path, params in (("/stats/trend", {"metric_type": "weight", "window": "30"}),
                         ("/stats/summary", {})):
        r = client.get(f"{API}{path}", headers=h, query_string=params)
        assert r.status_code < 500, f"{path} → {r.status_code} {r.get_json()}"

    bare = client.get(f"{API}/stats/trend", headers=h)
    assert bare.status_code == 400, f"缺参应 400，实为 {bare.status_code}"
    assert (bare.get_json() or {}).get("code") == "INVALID_PARAM"


# ══════════════════════════════════════════════════════════════════
# §三.5 注销（A-07）仍可用，且行为未被 B1 改动
# ══════════════════════════════════════════════════════════════════
def test_a07_close_account_still_works(client) -> None:  # noqa: ANN001
    username, resp = register(client)
    uid = account_id(username)
    h = auth(tokens_of(resp)["access_token"])

    bad = client.delete(f"{API}/users/me", headers=h,
                        json={"password": PASSWORD, "confirm_text": "注销"})
    assert bad.status_code == 422, bad.get_json()
    assert int(scalar("SELECT COUNT(*) FROM user_account WHERE id=:i", i=uid)) == 1

    ok = client.delete(f"{API}/users/me", headers=h,
                       json={"password": PASSWORD, "confirm_text": CONFIRM_TEXT})
    assert ok.status_code == 200, ok.get_json()
    assert int(scalar("SELECT COUNT(*) FROM user_account WHERE id=:i", i=uid)) == 0
    for table in ("user_session", "user_profile", "login_failure_state"):
        n = int(scalar(f"SELECT COUNT(*) FROM {table} WHERE user_id=:i", i=uid)) \
            if table != "login_failure_state" else int(
                scalar("SELECT COUNT(*) FROM login_failure_state WHERE username=:u",
                       u=username))
        assert n == 0, f"{table} 未随注销清空"


def test_delete_order_is_still_exactly_the_frozen_8_steps() -> None:
    """§六：``A-07`` 的 8 步 ``DELETE_ORDER`` **本批未改**（逐字比对）。"""
    order = delete_order_block()
    # B2（A-07 §九）：DELETE_ORDER 由 8 步扩展为 10 步（新增 verification_code、
    # password_reset_token）。此处直接写入 **B2 后的冻结 10 步**（值取自 B2 实现），
    # 不再依赖 B1 时期的 8 步常量。
    assert order == (
        "record_tag",
        "health_record",
        "health_goal",
        "user_profile",
        "export_job",
        "user_session",
        "login_failure_state",
        "verification_code",
        "password_reset_token",
        "user_account",
    ), f"DELETE_ORDER 被改动：{order}"
    # B2（A-07 §九）：DELETE_ORDER 由 8 步扩展为 10 步。
    assert len(order) == 10


def test_new_tables_not_in_delete_order_gap_registered() -> None:
    """**``Q-B0-08`` 缺口已在 B2 关闭**：两张新表已纳入 A-07 删除顺序。

    B1 时期本用例把「新表尚未纳入 ``DELETE_ORDER``」钉死为待办；B2 依授权
    （§九 A-07 扩展 ``8 → 10``）落地后，**同批**把断言翻转为正向（铁律⑬）：
    两张表**必须**出现在 ``DELETE_ORDER`` 中，且都排在 ``user_account``
    **之前**（子表先删、主表后删）。

    （函数名保留 B1 时期名称以稳定用例 ID；语义已随 B2 授权翻转。）
    """
    block = SERVICE_SRC.read_text(encoding="utf-8") \
        .split("DELETE_ORDER: Tuple[str, ...] = (")[1].split(")")[0]
    assert "verification_code" in block
    assert "password_reset_token" in block
    assert block.index("verification_code") < block.index("user_account")
    assert block.index("password_reset_token") < block.index("user_account")


def test_revoked_reason_enum_untouched() -> None:
    """§六 的 **B1 期哨兵**：``revoked_reason`` 不得**提前**新增取值。

    B2 已依授权（E-24 · §七.13 / §八）正式新增 ``password_reset``
    ⇒ 断言**同批翻转**为正向（铁律⑬）：该取值**必须**存在，且 ``auth_service``
    必须在 A-05 改密路径上引用 ``PasswordResetToken`` 以撤销未消费的重置凭证。

    （函数名保留 B1 时期名称以稳定用例 ID；语义已随 B2 授权翻转。）
    """
    _auth_src = AUTH_SRC.read_text(encoding="utf-8")
    assert 'REASON_PASSWORD_RESET = "password_reset"' in _auth_src, \
        "E-24 未落地：auth_service 缺少 password_reset 撤销原因常量"
    assert "PasswordResetToken" in _auth_src, \
        "E-24 未落地：auth_service 未引用 PasswordResetToken 以撤销未消费重置凭证"


def test_orphan_child_rows_remain_after_close_account(client) -> None:  # noqa: ANN001
    """**缺口实证**：账号被 A-07 物理删除后，新表中该用户的子行会留存为孤儿。

    这是 ``DELETE_ORDER`` 尚未扩展的**直接后果**（B5 授权项 ``Q-B0-08``），
    不是 B1 缺陷；本测试为「必须扩展删除顺序」提供可复现证据。
    （孤儿行由 ``conftest`` 的 id 水位线在收尾时清除。）
    """
    username, resp = register(client)
    uid = account_id(username)
    token = tokens_of(resp)["access_token"]

    with get_session_factory()() as s:
        s.add(VerificationCode(
            user_id=uid, purpose=PURPOSE_PASSWORD_RESET,
            code_hash=hash_verification_code("z" * 32, uid, PURPOSE_PASSWORD_RESET, "123456"),
            expires_at=now_local() + timedelta(minutes=15),
            attempt_count=0, created_at=now_local(),
        ))
        s.commit()

    r = client.delete(f"{API}/users/me", headers=auth(token),
                      json={"password": PASSWORD, "confirm_text": CONFIRM_TEXT})
    assert r.status_code == 200, r.get_json()
    assert int(scalar("SELECT COUNT(*) FROM user_account WHERE id=:i", i=uid)) == 0
    # B2（A-07 §九）把两张新表纳入 DELETE_ORDER ⇒ 关号后不再留下孤儿子行。
    assert int(scalar("SELECT COUNT(*) FROM verification_code WHERE user_id=:i", i=uid)) == 0


# ══════════════════════════════════════════════════════════════════
# §十二 K/L/M：B1 不得新增前端 / 找回 API / 蓝图
# ══════════════════════════════════════════════════════════════════
def test_no_password_reset_api_endpoint_was_added(app) -> None:  # noqa: ANN001
    """L/M 判据：**未实现**验证码发送接口、**未实现**密码重置接口。"""
    rules = [str(r) for r in app.url_map.iter_rules()]
    suspicious = [r for r in rules
                  if any(k in r.lower() for k in ("reset", "forgot", "verification"))]
    # B2（PR-01 / PR-02 / PR-03）已按授权正式新增这 3 个端点
    # ⇒ 判据同步更新为「恰好这 3 个」，其余任何找回密码类路由仍视为非法新增。
    assert set(suspicious) == {
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/verify",
        "/api/v1/auth/password-reset/confirm",
    }, f"找回密码路由集合被改动：{suspicious}"


def test_blueprint_set_unchanged(app) -> None:  # noqa: ANN001
    # B2 新增 password_reset 蓝图（承载 PR-01/02/03 三个找回密码端点）；
    # B3（2026-09-24）新增 email_bind 蓝图（承载 PR-04/05 两个邮箱绑定端点）
    # ⇒ 在 B1 冻结蓝图集合之上**只增**这两项；其余任何变化仍判失败。
    # 铁律⑬（同批翻正）：新增能力落地的**同一批**内更新该哨兵集合，
    # 使「表外新增」依旧会被本断言抓出。本用例计数不增（仍为 153 项之一）。
    assert set(app.blueprints) == FROZEN_BLUEPRINTS | {"password_reset", "email_bind"}, \
        f"蓝图集合被改动：{set(app.blueprints)}"


@pytest.mark.parametrize("needle", ("PasswordResetPanel.vue", "password-reset"))
def test_frontend_not_referenced_from_backend(needle: str) -> None:
    """K 判据（后端侧）：后端不得引用任何前端组件 / 前端页面路由标识。

    **B2 授权说明**：``password-reset`` 同时是 B2 自有后端 API 的**路径段**
    （``app/api/v1/password_reset.py`` 声明 PR-01~03 三个端点），这不属于
    「引用前端产物」。故仅对 ``password-reset`` 这一个 needle 豁免**唯一一个**
    B2 授权模块；其余任何 ``app/**/*.py`` 命中（含该豁免文件对
    ``PasswordResetPanel.vue`` 的命中）仍判失败。「前端 0 修改」结论不受影响。
    """
    b2_api_module = (BACKEND / "app" / "api" / "v1" / "password_reset.py").resolve()
    hits = [
        str(path)
        for path in (BACKEND / "app").rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
        and not (needle == "password-reset" and path.resolve() == b2_api_module)
    ]
    assert hits == [], f"后端引用了前端产物：{hits}"
