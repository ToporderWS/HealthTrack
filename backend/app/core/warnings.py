# -*- coding: utf-8 -*-
"""字段级**软提示**（``warnings[]``）体系。

依据：
- 《S1-B 第二批 API 接口设计文档》§3.14「统一健康值校验契约（硬拦截 / 软提示分离）」
- 《S0-产品规划报告》§7.5「数值合理性校验（F-023）的设计边界」

分层口径（与 ``app.core.errors`` **不是同一层**）：
- ``ErrorCode``：**18 个全局错误码**，S2 第二批封板，**只增不改**。
- ``FieldErrorCode``：``errors[]`` 字段级**错误**码，S2 第二批封板。
- :class:`WarningCode`（本模块）：``warnings[]`` 字段级**警告**码。

> **本批（S2 第三批）新增独立的 ``warnings[]`` 警告体系，
> 不扩充 S2 第二批已封板的 ``FieldErrorCode``。**
> ``warnings[]`` 只在 **HTTP 200 + ``SOFT_WARNING``** 响应中出现，**不是错误**。

**红线**（全项目强制，不得放宽）：
- 软提示文案统一为「该数值超出常见录入范围，请确认是否输错」；
- **不做**医学判断、**不给**建议、**不展示**参考区间、**不出现**任何评价性表述；
- 文案只用于识别「录入错误」，不得据此给出任何结论。
"""
from __future__ import annotations

from typing import Any, Dict, List

#: 软提示统一文案（S0 §7.5 四 / S1-B §3.14：唯一允许的模板）
SOFT_WARNING_MESSAGE = "该数值超出常见录入范围，请确认是否输错"


class WarningCode:
    """字段级警告码（独立体系，**不进入** ``ErrorCode`` / ``FieldErrorCode``）。"""

    #: 数值落在「疑似录入错误」区间之外（仍可能真实存在 → 只提示，不阻断）
    OUT_OF_COMMON_RANGE = "OUT_OF_COMMON_RANGE"


def warn(field: str, code: str, message: str = SOFT_WARNING_MESSAGE) -> Dict[str, Any]:
    """构造一条 ``warnings[]`` 元素。"""
    return {"field": field, "code": code, "message": message}


def out_of_range(field: str) -> Dict[str, Any]:
    """「超出常见录入范围」软提示（统一文案）。"""
    return warn(field, WarningCode.OUT_OF_COMMON_RANGE)


def soft_warning_payload(warnings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """软提示（未写入）响应的 ``data`` 载荷。

    §3.14：软提示 = **HTTP 200 + ``SOFT_WARNING``**，**本次不写入**，
    客户端展示确认后「**原样重发同一请求 + ``acknowledge_warnings: true``**」。
    """
    return {"requires_confirm": True, "warnings": list(warnings or [])}


__all__ = [
    "WarningCode",
    "SOFT_WARNING_MESSAGE",
    "warn",
    "out_of_range",
    "soft_warning_payload",
]
