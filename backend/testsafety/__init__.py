# -*- coding: utf-8 -*-
"""B1-R-FIX · 测试安全包（**工程级测试安全基础设施**）。

为什么不是 ``backend/app/core/``（S3 要求）
------------------------------------------
- ``app/`` 是**产品业务运行链**：产品代码**不得**依赖测试安全配置；
- 本包位于 ``backend/testsafety/``（``app/`` 之外），仅被
  ``backend/conftest.py`` 与 ``backend/tests/**`` 引用；
- ``tests/__init__.py`` 存在 ⇒ pytest 以 ``prepend`` 方式把 ``backend/`` 插入
  ``sys.path`` ⇒ ``import testsafety`` 天然可用，无需安装、无需改 ``pytest.ini``。

模块
----
``protected_assets``
    单一权威保护名单（PROTECTED_USERNAMES / PROTECTED_USER_IDS /
    永久历史 denylist / 独占前缀）＋ 指纹自校验。
``guard``
    公共安全守卫：D0 专用测试库 fail-closed、C 本次创建集合、
    A denylist、B 独占前缀（辅助），以 SQLAlchemy **引擎级**咽喉点统一执行。
"""

__all__ = ["protected_assets", "guard"]
