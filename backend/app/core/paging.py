# -*- coding: utf-8 -*-
"""游标分页与时间范围解析工具。

依据：《S1-B 第二批 API 接口设计文档》
- §3.9 分页规则（keyset）：``limit`` 默认 20、可选 20/50/100；排序固定
  ``recorded_at DESC, id DESC``；``cursor = base64url({"t":"<recorded_at>","id":<id>})``，
  **对客户端不透明**；**不返回 total**；**非法 cursor → 400**（不得回退为"从头发"）
- §3.10 时间范围规则：**半开区间 `[start, end)`**；``start >= end`` → ``400 INVALID_PARAM``
- §3.8 时间字段格式：``YYYY-MM-DD HH:mm:ss``（本地墙上时间，**无时区后缀**，不接受带 ``Z`` / 偏移）
"""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any, Optional, Tuple

from app.core.errors import ApiError, ErrorCode

#: ``limit`` 允许取值（§3.9：默认 20，可选 20/50，上限 100）
ALLOWED_LIMITS: Tuple[int, ...] = (20, 50, 100)
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def parse_limit(raw: Optional[str]) -> int:
    """解析 ``limit`` 查询参数（非法 → ``400 INVALID_PARAM``）。"""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_LIMIT
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError(ErrorCode.INVALID_PARAM)
    if value not in ALLOWED_LIMITS or value > MAX_LIMIT:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return value


def encode_cursor(recorded_at: datetime, record_id: int) -> str:
    """构造 ``next_cursor``（``base64url`` 去填充；对客户端不透明）。"""
    payload = {"t": recorded_at.strftime(DATETIME_FORMAT), "id": int(record_id)}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(raw: str) -> Tuple[datetime, int]:
    """解析 ``cursor``；任何异常 → ``400 INVALID_PARAM``（**不回退**）。"""
    text = (raw or "").strip()
    if not text:
        raise ApiError(ErrorCode.INVALID_PARAM)
    try:
        padded = text + "=" * (-len(text) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        recorded_at = datetime.strptime(str(data["t"]), DATETIME_FORMAT)
        record_id = int(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(ErrorCode.INVALID_PARAM)
    if record_id <= 0:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return recorded_at, record_id


def format_dt(value: Optional[datetime]) -> Optional[str]:
    """按 §3.8 输出 ``YYYY-MM-DD HH:mm:ss``。"""
    return value.strftime(DATETIME_FORMAT) if value else None


def parse_body_datetime(field: str, raw: Any) -> Optional[datetime]:
    """请求体时间字段：仅接受 ``YYYY-MM-DD HH:mm:ss``；失败 → ``422 VALIDATION_FAILED``。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATETIME_FORMAT)
    except ValueError:
        from app.core.errors import FieldErrorCode, field_error, validation_error

        raise validation_error(
            [field_error(field, FieldErrorCode.INVALID_FORMAT, "时间格式应为 YYYY-MM-DD HH:mm:ss")]
        )


def parse_range_bound(field: str, raw: Optional[str]) -> Optional[datetime]:
    """``start`` / ``end`` 查询参数：接受日期或日期时间；失败 → ``400 INVALID_PARAM``。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATETIME_FORMAT)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, DATE_FORMAT)
    except ValueError:
        raise ApiError(ErrorCode.INVALID_PARAM)


def parse_range(start_raw: Optional[str], end_raw: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """解析半开区间 ``[start, end)``；``start >= end`` → ``400``。"""
    start = parse_range_bound("start", start_raw)
    end = parse_range_bound("end", end_raw)
    if start is not None and end is not None and start >= end:
        raise ApiError(ErrorCode.INVALID_PARAM)
    return start, end


__all__ = [
    "ALLOWED_LIMITS",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "DATETIME_FORMAT",
    "DATE_FORMAT",
    "parse_limit",
    "encode_cursor",
    "decode_cursor",
    "format_dt",
    "parse_body_datetime",
    "parse_range",
]
