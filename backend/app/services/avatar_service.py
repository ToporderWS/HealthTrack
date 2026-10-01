# -*- coding: utf-8 -*-
"""头像服务（S4-2B：**AV-01 / AV-02 / AV-03 的服务层**）。

依据：《康迹 HealthTrack · S4-2A 头像上传技术方案与开工前审计报告》（需求方 2026-09-22 审核通过）

冻结口径（**逐条落实，不发明规则**）：

- **存储**：`AVATAR_DIR`（默认 `backend/storage/avatars`，与 `EXPORT_DIR` 同级），
  **DB 只存服务端生成的 basename**（`secrets.token_hex(16)` + 服务端判定扩展名）；
  **绝不挂 Flask `static`** —— 否则将产生无鉴权暴露 + 绕过 `X-Request-Id` + 隐式路由。
- **格式判定**：**只看字节签名（magic bytes）**，**不信任 `Content-Type`、不信任扩展名、
  不信任原始文件名**；白名单 = JPEG / PNG / WebP（**GIF / SVG / HEIC 一律拒绝**）。
  （Python 3.13 已移除标准库 `imghdr` ⇒ 此处为**手写签名表**，零依赖、面向未来。）
- **大小上限**：`AVATAR_MAX_BYTES`（默认 2 MiB）。**不使用全局 `MAX_CONTENT_LENGTH`**
  —— 它会产出 `413`，而 `413` 不在 18 个冻结错误码内 ⇒ 语义错乱；
  改为**分块实读 `limit + 1` 字节**，超限判 `422`。
- **不做服务端重编码 / 裁剪**：**不引入 Pillow、不引入任何第三方图片库**（需求方明令）；
  展示层用 `mode="aspectFill"` + 圆角裁切。
- **原始文件名**：**不落盘、不入库、不入日志、不入响应**（结构上排除路径穿越）。
- **鉴权**：三个端点**全部 `@require_auth`**；`user_id` 只来自 Access Token。
- **不变式**：`avatar_key` 与 `avatar_updated_at` **同写同清**（要么都非空、要么都为空）。
- **更换序**：**先落新文件 → 再 UPSERT 提交 → 提交成功后清旧文件**；
  提交失败 ⇒ 回滚并**删除刚写入的新文件**（不留孤儿）；旧文件清理失败 ⇒
  **不得影响主流程结果**（仍返回成功），登记到**独立** `avatar_cleanup_retry.jsonl`。
- **独立重试队列（★ 不可复用 `cleanup_retry.jsonl`）**：既有
  :func:`account_service.drain_cleanup_retries` 的**唯一解析根是 `EXPORT_DIR`**，
  头像文件在其中**永远找不到** ⇒ 复用会导致条目**永久滞留**；故本模块维护**独立队列**，
  **零改动**既有导出清理机制。
- **日志**：**只记 `request_id` 与结果码** —— 不记 `user_id` / `avatar_key` /
  原始文件名 / 完整路径 / 图片字节数（不可回溯到个人）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from flask import Response, current_app, request, send_file
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    ApiError,
    ErrorCode,
    FieldErrorCode,
    field_error,
    validation_error,
)
from app.core.request_id import get_request_id
from app.core.security import now_local
from app.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# ── 随机 key 与文件名 ───────────────────────────────────────────────
#: 随机字节数：16 字节 = 32 位十六进制（与 `export_job.file_token` 同口径）
AVATAR_KEY_BYTES = 16

#: 合法 key 形态（**严格白名单**：32 位小写十六进制 + 服务端判定扩展名）
#: 即便 DB 被污染，非法 key 也**永远不会**被拼进文件系统路径。
AVATAR_KEY_RE = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")

# ── 格式白名单（字节签名 → 规范名）──────────────────────────────────
#: JPEG：`FF D8 FF`
JPEG_MAGIC = b"\xff\xd8\xff"
#: PNG：8 字节固定签名
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
#: WebP：`RIFF` + 4 字节长度 + `WEBP`
WEBP_RIFF = b"RIFF"
WEBP_TAG = b"WEBP"

#: 规范名 → 服务端固定 MIME（**绝不由客户端指定**）
MIME_OF: Dict[str, str] = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
#: 规范名 → 落盘扩展名
EXT_OF: Dict[str, str] = {"jpeg": "jpg", "png": "png", "webp": "webp"}
#: 扩展名 → 规范名（**只用于服务端自查**，不用于判定上传内容）
FORMAT_OF_EXT: Dict[str, str] = {v: k for k, v in EXT_OF.items()}
#: 允许的规范名（白名单，顺序即文档序）
ALLOWED_FORMATS: Tuple[str, ...] = ("jpeg", "png", "webp")

#: 重试登记队列文件名（落盘于 `AVATAR_DIR` 的**父目录**＝`storage/` 根；不入业务库）
AVATAR_RETRY_FILENAME = "avatar_cleanup_retry.jsonl"

#: 上传字段名（冻结：`file`）
UPLOAD_FIELD = "file"

#: 成功文案（冻结）
UPDATED_MESSAGE = "头像已更新"
CLEARED_MESSAGE = "已恢复默认头像"

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# ════════════════════════════════════════════════════════════════════
# 配置读取
# ════════════════════════════════════════════════════════════════════
def avatar_dir() -> str:
    """头像目录（`AVATAR_DIR`；由 `_resolve_dir()` 解析为 backend/ 下绝对路径）。"""
    return str(current_app.config.get("AVATAR_DIR") or "")


def max_bytes() -> int:
    """上传大小上限（`AVATAR_MAX_BYTES`，默认 2 MiB）。"""
    try:
        return int(current_app.config.get("AVATAR_MAX_BYTES") or 2 * 1024 * 1024)
    except (TypeError, ValueError):
        return 2 * 1024 * 1024


def _rid() -> str:
    return get_request_id()


# ════════════════════════════════════════════════════════════════════
# 字节签名嗅探（**唯一可信的格式判定**）
# ════════════════════════════════════════════════════════════════════
def sniff_format(head: bytes) -> Optional[str]:
    """按字节签名判定真实格式；不在白名单内（含 GIF / SVG / HEIC / 任意二进制）→ `None`。

    **不读取 `Content-Type`、不读取扩展名、不读取原始文件名** —— 三者均可伪造。
    """
    if not head:
        return None
    if head.startswith(PNG_MAGIC):
        return "png"
    if head.startswith(JPEG_MAGIC):
        return "jpeg"
    if len(head) >= 12 and head[0:4] == WEBP_RIFF and head[8:12] == WEBP_TAG:
        return "webp"
    return None


def new_avatar_key(fmt: str) -> str:
    """服务端生成 basename：`token_hex(16)` + 服务端判定扩展名。"""
    ext = EXT_OF.get(str(fmt))
    if ext is None:
        raise ValueError("不支持的图片格式")
    return f"{secrets.token_hex(AVATAR_KEY_BYTES)}.{ext}"


def mime_of_key(key: Optional[str]) -> Optional[str]:
    """由 basename 推导 MIME（**服务端固定映射**，不由客户端指定）。"""
    if not key or "." not in key:
        return None
    fmt = FORMAT_OF_EXT.get(str(key).rsplit(".", 1)[-1].lower())
    return MIME_OF.get(fmt) if fmt else None


# ════════════════════════════════════════════════════════════════════
# 文件系统（受 `AVATAR_DIR` 约束，**不接受客户端路径**）
# ════════════════════════════════════════════════════════════════════
def _avatar_base_real() -> str:
    """`AVATAR_DIR` 的规范化真实路径（头像文件处置的**唯一合法根**）。"""
    base = avatar_dir()
    if not base:
        raise OSError("AVATAR_DIR 未配置")
    return os.path.realpath(base)


def avatar_retry_queue_path() -> str:
    """重试登记文件路径（与 `AVATAR_DIR` **同级**的 storage 根；不入业务库）。"""
    return os.path.join(os.path.dirname(_avatar_base_real()), AVATAR_RETRY_FILENAME)


def safe_avatar_path(key: Any) -> Optional[str]:
    """把库内 `avatar_key` 收敛为**必须位于 `AVATAR_DIR` 内**的真实路径。

    双闸门：
    1. **形态白名单** —— 必须匹配 :data:`AVATAR_KEY_RE`（32 位十六进制 + 白名单扩展名），
       结构上不可能含路径分隔符 / `..` / 绝对路径；
    2. **真实路径包含** —— `os.path.realpath` + `os.path.commonpath` 必须仍在根内
       （`ValueError`（不同盘符 / 混合路径）视为越界）。

    任一不满足 → `None`（**不返回任何路径、不触碰任何文件**）。
    """
    if not key:
        return None
    text = str(key)
    if os.path.basename(text) != text or not AVATAR_KEY_RE.match(text):
        return None
    base_real = _avatar_base_real()
    target = os.path.realpath(os.path.join(base_real, text))
    try:
        inside = os.path.commonpath([base_real, target]) == base_real
    except ValueError:  # 混合绝对/相对路径、不同盘符
        inside = False
    return target if inside else None


def _unlink(path: str) -> None:
    """**实际删除文件的原语**（本模块唯一删除入口；便于测试注入失败以验证重试分支）。"""
    os.remove(path)


def _remove_avatar_file(key: Any) -> None:
    """删除一个头像文件；key 非法 / 越界 → 抛 `ValueError`；文件已不存在 → 幂等成功。"""
    target = safe_avatar_path(key)
    if target is None:
        raise ValueError("头像 key 非法或路径越界")
    if not os.path.isfile(target):
        return                      # 已不存在 ⇒ 视为已清理（幂等）
    _unlink(target)


def _write_avatar_file(content: bytes, fmt: str) -> str:
    """落盘到 `AVATAR_DIR` 下的**服务端生成文件名**（客户端无法指定路径）。"""
    base = _avatar_base_real()
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, new_avatar_key(fmt))
    with open(path, "wb") as handle:
        handle.write(content)
    return path


# ════════════════════════════════════════════════════════════════════
# 独立重试登记队列（★ 不复用导出队列：解析根不同）
# ════════════════════════════════════════════════════════════════════
def _read_retry_queue() -> List[Dict[str, Any]]:
    path = avatar_retry_queue_path()
    if not os.path.isfile(path):
        return []
    items: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    entry = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("file_name"):
                    items.append(entry)
    except OSError:
        logger.warning("头像重试队列读取失败（code=OSError）")
        return []
    return items


def _write_retry_queue(items: Sequence[Dict[str, Any]]) -> None:
    path = avatar_retry_queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in items:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def enqueue_avatar_cleanup_retry(file_name: str, code: str, attempt: int = 1) -> None:
    """登记一条待重试的**头像**文件清理项。

    **只记录 basename** —— 不记录 `user_id`、不记录完整路径、不记录原始文件名。
    """
    name = os.path.basename(str(file_name or ""))
    if not name:
        return
    path = avatar_retry_queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {
        "file_name": name,
        "attempt": int(attempt),
        "code": str(code),
        "ts": now_local().strftime(DATETIME_FORMAT),
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def drain_avatar_cleanup_retries() -> Tuple[int, int]:
    """重放已登记的待清理**头像**文件（真实可执行的最小重试机制）。

    - 逐条尝试删除 `AVATAR_DIR / <file_name>`；成功或文件已不存在 → 移出队列；
    - 仍失败 → `attempt + 1` 保留登记，并写**脱敏**告警日志；
    - **无后台 worker / 定时任务** ⇒ 由下一次头像变更 / 注销流程**顺带调用**。

    返回 `(cleared, remaining)`。
    """
    items = _read_retry_queue()
    if not items:
        return 0, 0

    base_real = _avatar_base_real()
    remaining: List[Dict[str, Any]] = []
    cleared = 0
    for entry in items:
        name = os.path.basename(str(entry.get("file_name") or ""))
        if not AVATAR_KEY_RE.match(name):
            entry["attempt"] = int(entry.get("attempt") or 1) + 1
            entry["code"] = "InvalidKey"
            entry["ts"] = now_local().strftime(DATETIME_FORMAT)
            remaining.append(entry)
            logger.warning("头像重试清理失败（attempt=%s code=InvalidKey）", entry["attempt"])
            continue
        target = os.path.join(base_real, name)
        try:
            if os.path.isfile(target):
                _unlink(target)
            cleared += 1
        except OSError as exc:
            entry["attempt"] = int(entry.get("attempt") or 1) + 1
            entry["code"] = type(exc).__name__
            entry["ts"] = now_local().strftime(DATETIME_FORMAT)
            remaining.append(entry)
            logger.warning(
                "头像重试清理失败（attempt=%s code=%s）", entry["attempt"], entry["code"]
            )
    _write_retry_queue(remaining)
    return cleared, len(remaining)


def cleanup_avatar_files(keys: Sequence[Any]) -> Tuple[int, int]:
    """**事务提交后**删除头像文件；失败 → 登记独立重试队列（**绝不回滚已提交的变更**）。

    - `OSError`（真删除失败）→ 计数 + **登记重试**；
    - `ValueError`（key 非法 / 越界）→ 数据异常，**安全拒绝删除**、只写脱敏告警、**不登记重试**；
    - 结束后顺带 **drain** 一次（opportunistic，与 A-07 的导出清理同构）。

    返回 `(failed, retry_remaining)`。
    """
    failed = 0
    for key in keys:
        try:
            _remove_avatar_file(key)
        except ValueError:
            logger.warning("头像 key 非法或越界，已拒绝删除（code=ValueError）")
        except OSError as exc:
            failed += 1
            enqueue_avatar_cleanup_retry(os.path.basename(str(key or "")), type(exc).__name__)
            logger.warning("头像清理失败，已登记重试（attempt=1 code=%s）", type(exc).__name__)
    _cleared, remaining = drain_avatar_cleanup_retries()
    return failed, remaining


# ════════════════════════════════════════════════════════════════════
# 读取请求体（**分块实读**，不用全局 MAX_CONTENT_LENGTH）
# ════════════════════════════════════════════════════════════════════
def _require_multipart_upload(files: Any, form: Any) -> Any:
    """取得 `file` 字段；缺失 / 非 multipart → `400 INVALID_PARAM`（携带字段级明细）。"""
    if form is not None and "user_id" in form:
        # multipart 的 form 字段不经过全局 JSON 守卫（`request.is_json` 为 False）
        # ⇒ 在此**就地**维持冻结语义：任何客户端提交的 `user_id` 一律 400。
        raise ApiError(ErrorCode.INVALID_PARAM)
    storage = files.get(UPLOAD_FIELD) if files is not None else None
    if storage is None or not getattr(storage, "filename", None):
        raise ApiError(ErrorCode.INVALID_PARAM, errors=[
            field_error(UPLOAD_FIELD, FieldErrorCode.REQUIRED, "请选择要上传的图片")
        ])
    return storage


def _read_checked_bytes(storage: Any) -> Tuple[bytes, str]:
    """分块实读 + 上限 + 签名校验。返回 `(字节, 规范格式名)`。

    - 空文件 → `422`；
    - 超出 `AVATAR_MAX_BYTES` → `422`（**多读 1 字节即判定**，不依赖 `Content-Length`）；
    - 签名不在白名单（GIF / SVG / HEIC / 文本 / 任意二进制 / 伪 MIME / 伪扩展名）→ `422`。
    """
    limit = max_bytes()
    try:
        data = storage.stream.read(limit + 1)
    except OSError:
        logger.exception("头像上传读取失败（request_id=%s）", _rid())
        raise ApiError(ErrorCode.INTERNAL_ERROR)
    if data is None:
        data = b""
    if not data:
        raise validation_error([
            field_error(UPLOAD_FIELD, FieldErrorCode.INVALID_FORMAT, "图片内容为空")
        ])
    if len(data) > limit:
        raise validation_error([
            field_error(UPLOAD_FIELD, FieldErrorCode.INVALID_FORMAT,
                        "图片大小超出上限（最大 2 MiB）")
        ])
    fmt = sniff_format(data)
    if fmt is None:
        raise validation_error([
            field_error(UPLOAD_FIELD, FieldErrorCode.INVALID_FORMAT,
                        "仅支持 JPEG / PNG / WebP 图片")
        ])
    return data, fmt


# ════════════════════════════════════════════════════════════════════
# 档案行读写（**只碰 avatar_key / avatar_updated_at 两列**）
# ════════════════════════════════════════════════════════════════════
def _load_profile(db: Session, user_id: int) -> Optional[UserProfile]:
    return db.execute(
        select(UserProfile).where(UserProfile.user_id == int(user_id))
    ).scalars().first()


def _upsert_profile(db: Session, user_id: int) -> UserProfile:
    profile = _load_profile(db, user_id)
    if profile is None:
        now = now_local()
        profile = UserProfile(user_id=int(user_id), created_at=now, updated_at=now)
        db.add(profile)
    return profile


def _avatar_view(profile: Optional[UserProfile]) -> Dict[str, Any]:
    """对外视图：**只有** `avatar_updated_at` —— 无 `avatar_key`、无路径、无可复制地址。"""
    stamp = None
    if profile is not None and profile.avatar_key and profile.avatar_updated_at:
        stamp = profile.avatar_updated_at.strftime(DATETIME_FORMAT)
    return {"avatar_updated_at": stamp}


# ════════════════════════════════════════════════════════════════════
# AV-01 上传 / 更换
# ════════════════════════════════════════════════════════════════════
def save_avatar(db: Session, *, user_id: int, files: Any,
                form: Any = None) -> Dict[str, Any]:
    """AV-01：上传或更换头像（**先落新文件 → 再 UPSERT → 提交后清旧文件**）。

    返回 `{"avatar_updated_at": "YYYY-MM-DD HH:mm:ss"}`。
    """
    storage = _require_multipart_upload(files, form)
    content, fmt = _read_checked_bytes(storage)

    # ── ① 先落盘新文件（尚未改库）──
    try:
        new_path = _write_avatar_file(content, fmt)
    except OSError:
        logger.exception("头像写入失败（request_id=%s）", _rid())
        raise ApiError(ErrorCode.INTERNAL_ERROR)
    new_key = os.path.basename(new_path)

    profile = _upsert_profile(db, user_id)
    old_key = profile.avatar_key
    now = now_local()
    profile.avatar_key = new_key
    profile.avatar_updated_at = now
    profile.updated_at = now

    # ── ② 提交；失败 ⇒ 回滚 + 删除刚写入的新文件（不留孤儿）──
    try:
        db.commit()
        db.refresh(profile)
    except Exception:
        db.rollback()
        try:
            _remove_avatar_file(new_key)
        except (OSError, ValueError):
            pass                     # 清理失败不影响"变更已失败"这一结果
        logger.exception("头像提交失败，已回滚并清理新文件（request_id=%s）", _rid())
        raise ApiError(ErrorCode.INTERNAL_ERROR)

    # ── ③ 提交成功后清理旧文件（失败**不得**影响结果，仍返回成功）──
    if old_key and old_key != new_key:
        cleanup_avatar_files([old_key])

    # ── ④ 脱敏日志：只有 request_id + 结果 ──
    logger.info("avatar_updated request_id=%s 结果=OK", _rid())
    return _avatar_view(profile)


# ════════════════════════════════════════════════════════════════════
# AV-02 删除 / 恢复默认（幂等）
# ════════════════════════════════════════════════════════════════════
def clear_avatar(db: Session, *, user_id: int) -> Dict[str, Any]:
    """AV-02：删除头像 / 恢复默认（**幂等**：无档案行 / 本就无头像 → 同样成功）。

    返回 `{"avatar_updated_at": None}`。
    """
    profile = _load_profile(db, user_id)
    old_key = profile.avatar_key if profile is not None else None

    if profile is not None and (profile.avatar_key or profile.avatar_updated_at):
        profile.avatar_key = None
        profile.avatar_updated_at = None
        profile.updated_at = now_local()
        db.commit()
        db.refresh(profile)

    if old_key:
        cleanup_avatar_files([old_key])

    logger.info("avatar_cleared request_id=%s 结果=OK（幂等）", _rid())
    return _avatar_view(profile)


# ════════════════════════════════════════════════════════════════════
# AV-03 读取本人头像（文件流）
# ════════════════════════════════════════════════════════════════════
def etag_of(key: str, size: int, updated_at: Optional[datetime]) -> str:
    """ETag：由**更新时间 + 字节数 + 扩展名**派生（**不依赖 `avatar_key`**）。

    说明：由不透明摘要构成（`sha256` 前 32 位十六进制），**不含 key、不含路径**，
    且不可反推；内容不可变（每次上传都换 key）⇒ 强缓存语义成立。
    """
    seed = "%s:%d:%s" % (updated_at.strftime(DATETIME_FORMAT) if updated_at else "-",
                         int(size), str(key).rsplit(".", 1)[-1])
    return '"' + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32] + '"'


def load_avatar(db: Session, *, user_id: int) -> Response:
    """AV-03：返回本人头像**文件流**（`@require_auth` 由路由层保证）。

    - 未设置头像（`avatar_key` 为空）→ `404 RESOURCE_NOT_FOUND`；
    - key 非法 / 越界 / 文件缺失 → `404`（**永不回退到目录枚举或路径拼接**）；
    - 响应头：`Content-Type`（**服务端固定映射**）/ `Content-Disposition: inline` /
      `Cache-Control: private, no-cache` / `ETag` / `Last-Modified` /
      `X-Content-Type-Options: nosniff` / `X-Request-Id`；
    - **响应体与响应头均不含 `avatar_key` / `user_id` / 服务器路径**。
    """
    profile = _load_profile(db, user_id)
    key = profile.avatar_key if profile is not None else None
    if not key:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    path = safe_avatar_path(key)
    if path is None or not os.path.isfile(path):
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    mime = mime_of_key(key)
    if mime is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    size = os.path.getsize(path)
    updated_at = profile.avatar_updated_at
    if updated_at is None:
        updated_at = datetime.fromtimestamp(os.path.getmtime(path))
    etag = etag_of(key, size, updated_at)
    last_modified = updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT")

    def _decorate(resp: Response) -> Response:
        resp.headers["Content-Type"] = mime
        resp.headers["Content-Disposition"] = "inline"
        resp.headers["Cache-Control"] = "private, no-cache"
        resp.headers["ETag"] = etag
        resp.headers["Last-Modified"] = last_modified
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Request-Id"] = _rid()
        return resp

    from flask import request

    if (request.headers.get("If-None-Match") or "").strip() == etag:
        # 条件命中 → 304（**不带实体**；客户端不发送 If-None-Match 时不会走到这里）
        return _decorate(Response(status=304))

    # 下载名 = 服务端固定名字（**不使用原始文件名**；`inline` 下仅作类型提示）
    ext = str(key).rsplit(".", 1)[-1]
    response: Response = send_file(
        path, mimetype=mime, as_attachment=False,
        download_name=f"avatar.{ext}", conditional=False,
    )
    return _decorate(response)


__all__ = [
    "ALLOWED_FORMATS",
    "AVATAR_KEY_BYTES",
    "AVATAR_KEY_RE",
    "AVATAR_RETRY_FILENAME",
    "CLEARED_MESSAGE",
    "EXT_OF",
    "MIME_OF",
    "UPLOAD_FIELD",
    "UPDATED_MESSAGE",
    "avatar_dir",
    "avatar_retry_queue_path",
    "cleanup_avatar_files",
    "clear_avatar",
    "drain_avatar_cleanup_retries",
    "enqueue_avatar_cleanup_retry",
    "etag_of",
    "load_avatar",
    "max_bytes",
    "mime_of_key",
    "new_avatar_key",
    "safe_avatar_path",
    "save_avatar",
    "sniff_format",
]
