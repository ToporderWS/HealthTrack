# -*- coding: utf-8 -*-
"""B1-R-FIX · 测试安全 —— **单一权威保护名单**（S3）。

定位（为什么放在 ``backend/testsafety/`` 而不是 ``backend/app/core/``）
----------------------------------------------------------------------
1. **不属于产品业务运行链**：``app/`` 下的任何模块都**不 import 本包**
   （已由 ``testsafety/guard.py`` 的同包断言 + 交付报告的静态扫描双重证明）；
2. **产品代码不得依赖它**：本包只被 ``backend/conftest.py`` 与 ``backend/tests/**`` 引用；
3. **pytest 可统一引用**：``tests/__init__.py`` 存在 ⇒ pytest 以 ``prepend`` 方式把
   ``backend/`` 插入 ``sys.path`` ⇒ ``import testsafety`` 天然可用；
4. **普通测试不得随意改写**：常量为 ``tuple``（不可变）＋ ``verify()`` 指纹自校验
   ＋ ``guard.py`` 交叉持有的 ``MANDATORY_*`` 下限断言（**两处都改才能削弱**，见下）。

**为什么不用 ``LIKE 'tst%'`` 判断保护对象**
------------------------------------------------
``tst`` 前缀是本项目的历史测试账号约定，但**它不能作为「可否删除」的依据**：
B1-R 事故中被物理删除的 ``tst35ro1`` / ``tstd02`` 恰恰就是 ``tst`` 前缀账号，
且它们**在测试启动前既已存在**。因此本名单以**显式枚举**为准，前缀只作辅助。

**关于已误删账号**
------------------
``tst35ro1`` / ``tstd02``（及 09-20 删除的 ``tsta7``）**已不存在**，
**不得**把它们写成「仍存在的保护对象」（S4：不伪造恢复）。
它们进入 ``PERMANENT_DENYLIST_*``：语义是「**此后任何 cleanup 都不得自动删除
名为/号为它的对象**」——防止同名对象日后被再次自动清除。
"""
from __future__ import annotations

import hashlib
from typing import Tuple

# ── 数据库名（D0 专用测试库）────────────────────────────────────────────
#: pytest **唯一**允许连接的数据库（``guard.assert_on_test_database`` 的期望值）
TEST_DATABASE: str = "kangji_healthtrack_test"
#: 开发库名——pytest 下**绝不允许**触碰；仅用于报告与断言的反面描述
DEV_DATABASE: str = "kangji_healthtrack"

# ── A 层：显式 denylist（既有正式 / 保护账号）──────────────────────────
#: 权威保护用户名（V1.0 现存正式账号 / 验收账号；2026-09-24 只读实测）
PROTECTED_USERNAMES: Tuple[str, ...] = ("top001", "top002", "top003", "toptest1")
#: 权威保护 user_id（与上表**逐一对应**；2026-09-24 只读实测
#: ``top001=4833 / top002=4834 / toptest1=4836 / top003=4838``）
PROTECTED_USER_IDS: Tuple[int, ...] = (4833, 4834, 4836, 4838)

# ── 永久历史 denylist（B1-R 事故中被误删；不得伪造为「仍存在」）──────
#: 历史被误删 / 已删除的测试账号名（B1 误删 2 个 + 09-20 删除 1 个）
PERMANENT_DENYLIST_USERNAMES: Tuple[str, ...] = ("tst35ro1", "tstd02", "tsta7")
#: 与之对应的历史 user_id（同上，均为「已不存在」，仅作防复活依据）
PERMANENT_DENYLIST_USER_IDS: Tuple[int, ...] = (4837, 4840, 4839)

# ── B 层：本批独占前缀（仅作辅助定位，**不得单独作为删除依据**）──────
#: 历史 / 现行测试账号前缀。用途仅限于「**在 id 水位线之内**定位本批新建行」的辅助。
#: ⚠️ 任何 cleanup 都**不得**仅凭此前缀删除（见 ``guard.evaluate_candidates``）。
TEST_USERNAME_PREFIX: str = "tst"


def canonical_payload() -> str:
    """把名单序列化为**确定性**字符串（用于指纹）。"""
    return "\n".join(
        [
            "test_db=" + TEST_DATABASE,
            "dev_db=" + DEV_DATABASE,
            "protected_usernames=" + ",".join(PROTECTED_USERNAMES),
            "protected_ids=" + ",".join(str(i) for i in PROTECTED_USER_IDS),
            "denylist_usernames=" + ",".join(PERMANENT_DENYLIST_USERNAMES),
            "denylist_ids=" + ",".join(str(i) for i in PERMANENT_DENYLIST_USER_IDS),
            "prefix=" + TEST_USERNAME_PREFIX,
        ]
    )


def fingerprint() -> str:
    """当前名单的 SHA-256（十六进制）。"""
    return hashlib.sha256(canonical_payload().encode("utf-8")).hexdigest()


#: 冻结指纹。**任何**对名单的增删改都会使 ``verify()`` 失败 ⇒ 改动必须显式复核。
#: （2026-09-24 固化；SHA-256 of ``canonical_payload()``）
EXPECTED_FINGERPRINT: str = "a0baed6f5862325b646c04e3e86c24577c7803029674e1a1f67b6a5996d6f35b"


class ProtectedAssetsTampered(RuntimeError):
    """保护名单被改写（指纹不符）。"""


def verify() -> str:
    """校验名单未被静默改写；返回当前指纹。"""
    actual = fingerprint()
    if EXPECTED_FINGERPRINT == "__PENDING__":
        raise ProtectedAssetsTampered(
            "EXPECTED_FINGERPRINT 尚未固化（工程缺陷）：请重新固化指纹后再运行测试"
        )
    if actual != EXPECTED_FINGERPRINT:
        raise ProtectedAssetsTampered(
            "保护名单指纹不符 —— 名单已被改写！\n"
            f"  expected = {EXPECTED_FINGERPRINT}\n"
            f"  actual   = {actual}\n"
            "如确属有意变更，必须同步更新 EXPECTED_FINGERPRINT 并重新评审。"
        )
    return actual
