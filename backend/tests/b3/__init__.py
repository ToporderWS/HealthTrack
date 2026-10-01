# -*- coding: utf-8 -*-
"""B3 邮箱绑定（A2 后端能力）—— 独立测试包。

与 ``tests/b2`` / ``tests/pwreset`` **完全隔离**（另建目录是需求方 §八 的硬要求）：
- ``pytest tests/b3``  ⇒ 只跑本批；
- ``pytest tests/b2``  ⇒ 47 项，**不受影响**；
- ``pytest tests/pwreset`` ⇒ 153 项，**不受影响**。
"""
