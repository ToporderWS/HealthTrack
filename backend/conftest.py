# -*- coding: utf-8 -*-
"""B1-R-FIX · **pytest 根级 conftest** —— 测试安全守卫的最早挂载点。

为什么放在 ``backend/conftest.py``（而不是改 ``tests/conftest.py``）
--------------------------------------------------------------------
pytest 按 **rootdir → 子目录** 的顺序加载 conftest：``backend/conftest.py`` 先于
``tests/conftest.py``（以及 ``tests/batch*/conftest.py``）被导入。因此这里可以在
**任何** ``load_config()`` / ``create_engine()`` **之前**把 ``MYSQL_DB`` 钉死为测试库，
并把守卫装到 SQLAlchemy 引擎级事件上——此后无论哪一个 conftest 里的 cleanup
发起 DELETE，都会先经过守卫。

三层时序
--------
1. **导入期**（本文件顶格代码）：``force_test_database()`` —— 钉死 ``MYSQL_DB``；
2. **pytest_configure**：``preflight_check()`` + ``assert_assets_intact()`` + ``install()``；
3. **pytest_sessionfinish / terminal_summary**：落盘审计产物（判决书证据）。

⚠️ 本文件**不修改**任何既有 conftest；既有 cleanup 代码原样保留，
安全性由引擎级守卫在**执行期**强制。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from testsafety import guard  # noqa: E402
from testsafety import protected_assets as PA  # noqa: E402

# ── ① 导入期：早于一切配置加载，钉死测试库（D0）──────────────────────
guard.force_test_database(os.environ)


def pytest_configure(config):  # noqa: ANN001
    import pytest

    try:
        guard.preflight_check(os.environ)
        guard.assert_assets_intact()
    except guard.TestSafetyViolation as ex:
        # 配置层不合格 ⇒ 直接中止整个 pytest 会话（FAIL-CLOSED，绝不 fallback）
        raise pytest.UsageError(str(ex)) from ex
    guard.install()
    try:
        guard.capture_watermark_eager()
    except guard.TestSafetyViolation as ex:
        # D0 在连接期发现库不符 ⇒ 继续 fail-closed
        raise pytest.UsageError(str(ex)) from ex
    except Exception:  # noqa: BLE001
        # 测试库尚未迁移等情形：留待首次 DELETE 时惰性取线（不影响安全）
        pass


def pytest_report_header(config):  # noqa: ANN001
    return [
        "testsafety D0 : 专用测试库 = %s（MYSQL_DB=%s）"
        % (guard.TEST_DATABASE, os.environ.get("MYSQL_DB")),
        "testsafety A  : 保护账号 = %s  ids=%s"
        % (",".join(PA.PROTECTED_USERNAMES), list(PA.PROTECTED_USER_IDS)),
        "testsafety A  : 永久 denylist = %s"
        % ",".join(PA.PERMANENT_DENYLIST_USERNAMES),
        "testsafety fp : %s" % PA.fingerprint()[:16],
    ]


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ANN001
    a = guard.audit()
    tr = terminalreporter
    tr.write_sep("=", "testsafety 守卫审计")
    tr.write_line(f"session            : {a['session']}")
    tr.write_line(f"测试库             : {a['test_database']}")
    tr.write_line(f"水位线已取值       : {a['watermark_taken']}")
    tr.write_line(f"受管表             : {len(a['guarded_tables'])} 张")
    tr.write_line(f"DELETE 经守卫      : {a['deletes_seen']} 条（放行 {a['deletes_allowed']}）")
    tr.write_line(f"否决(ABORT)        : {len(a['vetoes'])} 条")
    tr.write_line(f"含 LIKE 谓词的删除 : {len(a['prefix_predicates'])} 条")
    tr.write_line(f"保护名单指纹       : {a['assets_fingerprint'][:16]}")


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    try:
        p = guard.dump_audit()
        print(f"\n[testsafety] 审计已落盘：{p}")
    except Exception as ex:  # noqa: BLE001
        print(f"\n[testsafety] 审计落盘失败：{type(ex).__name__}: {ex}")
