# -*- coding: utf-8 -*-
"""``Idempotency-Key`` 请求幂等（进程内 TTL 缓存）。

依据：《S1-B 第二批 API 接口设计文档》§3.11「幂等性要求」

| 约定 | 口径 |
|---|---|
| 适用接口 | ``POST /records``、``POST /records/batch-delete``（本批） |
| 语义 | **同 key + 同请求体 → 返回首次结果**；**同 key + 不同请求体 → 409 ``IDEMPOTENCY_CONFLICT``** |
| 幂等窗口 | **10 分钟** |
| 是否强制 | **不强制**客户端携带（F-083 第一道防线在客户端置灰按钮） |

**★ 实现口径与已知限制（须在报告中如实登记）**

S1-B 冻结的 8 张业务表中**没有**幂等记录表，本批**不得新增表 / 新增迁移**，
因此幂等窗口以**进程内 TTL 缓存**实现：

- 优点：**零数据库变更**，覆盖「同一进程内的网络重试 / 连击」这一主要场景；
- 限制：① **不跨进程 / 不跨 worker 共享**；② 进程重启后窗口丢失。
- 若后续要求跨进程强幂等，需新增持久化幂等表（**属数据库结构变更，不在本批授权范围**）。

**回放口径**：命中时回放**首次的 ``code`` / ``message`` / ``data`` / HTTP 状态码**，
但 ``request_id`` **按本次请求重新生成**（§3.7：``request_id`` 每次请求唯一，
且必须与响应头 ``X-Request-Id`` 一致）。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Dict, Optional, Tuple

from app.core.errors import ApiError, ErrorCode

#: 幂等窗口（秒）——S1-B §3.11 冻结：10 分钟
IDEMPOTENCY_TTL_SECONDS = 600

#: 进程内缓存条目上限（防止无界增长）
MAX_ENTRIES = 512

#: 请求头名
IDEMPOTENCY_HEADER = "Idempotency-Key"

#: 幂等键长度约束（客户端生成 UUID；过短/过长视为非法参数）
KEY_MIN_LEN = 8
KEY_MAX_LEN = 128

_lock = threading.Lock()
#: {(user_id, key): {"body_hash": str, "status": int, "code": str, "message": str,
#:                   "data": Any, "expires_at": float, "used_at": float}}
_store: Dict[Tuple[int, str], Dict[str, Any]] = {}


def body_fingerprint(body: Any) -> str:
    """请求体指纹（用于判定「同 key 是否同请求体」）。"""
    try:
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         default=str)
    except (TypeError, ValueError):
        raw = repr(body)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prune(now: float) -> None:
    expired = [k for k, v in _store.items() if v["expires_at"] <= now]
    for k in expired:
        _store.pop(k, None)
    if len(_store) > MAX_ENTRIES:
        # 淘汰最早写入的条目
        for k, _ in sorted(_store.items(), key=lambda kv: kv[1]["used_at"])[: len(_store) - MAX_ENTRIES]:
            _store.pop(k, None)


def normalize_key(raw: Optional[str]) -> Optional[str]:
    """校验并归一化 ``Idempotency-Key``；未携带 → ``None``。"""
    if raw is None:
        return None
    key = str(raw).strip()
    if not key:
        return None
    if not (KEY_MIN_LEN <= len(key) <= KEY_MAX_LEN):
        raise ApiError(ErrorCode.INVALID_PARAM)
    return key


def lookup(user_id: int, key: Optional[str], body: Any) -> Optional[Dict[str, Any]]:
    """查幂等窗口。

    - 未携带 key → ``None``（不启用幂等）
    - 命中且**请求体一致** → 返回首次结果快照（调用方回放）
    - 命中但**请求体不同** → ``409 IDEMPOTENCY_CONFLICT``
    """
    if not key:
        return None
    now = time.time()
    with _lock:
        _prune(now)
        entry = _store.get((int(user_id), key))
        if entry is None:
            return None
        if entry["body_hash"] != body_fingerprint(body):
            raise ApiError(ErrorCode.IDEMPOTENCY_CONFLICT)
        entry["used_at"] = now
        return {
            "status": entry["status"],
            "code": entry["code"],
            "message": entry["message"],
            "data": entry["data"],
        }


def remember(user_id: int, key: Optional[str], body: Any, status: int, code: str,
             message: str, data: Any) -> None:
    """写入幂等窗口（仅**实际写入成功**的请求才登记）。"""
    if not key:
        return
    now = time.time()
    with _lock:
        _store[(int(user_id), key)] = {
            "body_hash": body_fingerprint(body),
            "status": int(status),
            "code": code,
            "message": message,
            "data": data,
            "expires_at": now + IDEMPOTENCY_TTL_SECONDS,
            "used_at": now,
        }
        _prune(now)


def reset() -> None:
    """清空窗口（仅供测试使用）。"""
    with _lock:
        _store.clear()


__all__ = [
    "IDEMPOTENCY_HEADER",
    "IDEMPOTENCY_TTL_SECONDS",
    "body_fingerprint",
    "normalize_key",
    "lookup",
    "remember",
    "reset",
]
