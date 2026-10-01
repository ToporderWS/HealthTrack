# -*- coding: utf-8 -*-
"""档案服务（P-01 获取档案 / P-02 更新档案）。

依据：
- 《S1-B 第二批 API 接口设计文档》§六 P-01 / P-02
- 《S1-D 技术方案最终冻结》**D-1**：目标体重唯一源 = ``health_goal``(``goal_type='weight'``)，
  ``user_profile`` **不建第二份字段**
- 《S0-产品规划报告》§7.5：输入合理性校验（软提示 / 硬拦截分离）

**红线**：档案中的文本字段（健康背景 / 过敏 / 药物输入）**只按用户原文存储与回显**，
**不做**任何解读、**不给**建议、**不产生**任何结论。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, ErrorCode, FieldErrorCode, field_error, validation_error
from app.core.security import now_local
from app.core.warnings import out_of_range
from app.models.health_record import HealthRecord
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile

#: 昵称最大长度
NICKNAME_MAX = 20
#: 文本字段最大长度（健康背景 / 过敏 / 药物输入）
TEXT_MAX = 2000
#: 性别枚举：0 未填 / 1 男 / 2 女
GENDERS = (0, 1, 2)
#: 血型枚举
BLOOD_TYPES = ("A", "B", "AB", "O", "UNKNOWN")
#: 出生日期下界
BIRTH_DATE_MIN = date(1900, 1, 1)

#: 录入合理性区间（**软提示**；来源 S1-B §六 P-02）
HEIGHT_SOFT = (Decimal("50"), Decimal("250"))
INITIAL_WEIGHT_SOFT = (Decimal("20"), Decimal("300"))

#: 存储上限（``Numeric(5,1)``，技术约束：超出即无法写入 → 硬拦截）
NUMERIC_5_1_MAX = Decimal("9999.9")

#: 文本字段名
TEXT_FIELDS = ("medical_history", "allergy_history", "medication_notes")

#: 目标体重取数指引（**D-1**：本接口不返回目标体重值，只给出取数来源）
TARGET_WEIGHT_GUIDANCE: Dict[str, str] = {
    "from": "health_goal",
    "available_at": "/api/v1/goals?goal_type=weight",
}

#: P-01 ``data.profile`` 的固定键集合（未填写字段**保留键并返回 null**，§3.13）
#: S4-2 追加 **1 键** ``avatar_updated_at``（**只暴露"头像最后更新时间"**；
#: **不返回 `avatar_key`、不返回服务器路径、不返回任何可复制资源地址**）。
PROFILE_KEYS = (
    "nickname", "gender", "birth_date", "age", "height_cm", "initial_weight_kg",
    "blood_type", "medical_history", "allergy_history", "medication_notes", "updated_at",
    "avatar_updated_at",
)

#: P-02 **可写字段白名单**（S4-2 加固）。
#: 头像两列（``avatar_key`` / ``avatar_updated_at``）**只能**经 AV-01 / AV-02 变更；
#: P-02（整体替换语义）**结构上不可能**覆盖或清空它们。
PROFILE_WRITE_FIELDS = (
    "nickname", "gender", "birth_date", "height_cm", "initial_weight_kg",
    "blood_type", "medical_history", "allergy_history", "medication_notes",
)


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _too_many_decimals(value: Decimal, allowed: int = 1) -> bool:
    """小数位是否超出业务精度（先 ``normalize()`` 去除无意义尾随零）。"""
    num = Decimal(value).normalize()
    if num == num.to_integral_value():
        return False
    return -num.as_tuple().exponent > allowed


def _out(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


def calc_age(birth: Optional[date], today: Optional[date] = None) -> Optional[int]:
    """按 ``birth_date`` 实时计算年龄（**派生值不落库**）。"""
    if birth is None:
        return None
    ref = today or now_local().date()
    years = ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))
    return years if years >= 0 else None


def latest_weight(db: Session, user_id: int) -> Optional[HealthRecord]:
    """最近一条**有效**体重记录（``is_deleted=0``；走 ``idx_hr_user_metric_time``）。"""
    return db.execute(
        select(HealthRecord)
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == "weight",
            HealthRecord.is_deleted == 0,
        )
        .order_by(HealthRecord.recorded_at.desc(), HealthRecord.id.desc())
        .limit(1)
    ).scalars().first()


def calc_bmi(weight_kg: Optional[Decimal], height_cm: Optional[Decimal]) -> Optional[Decimal]:
    """BMI = 体重(kg) ÷ 身高(m)²；任一缺失 → ``None``（**不补零、不估算**）。"""
    if weight_kg is None or height_cm is None:
        return None
    height_m = Decimal(height_cm) / Decimal("100")
    if height_m <= 0:
        return None
    return (Decimal(weight_kg) / (height_m * height_m)).quantize(Decimal("0.1"))


def profile_payload(profile: Optional[UserProfile]) -> Dict[str, Any]:
    """构造 ``data.profile``（未初始化 → **全 null 对象，不是 404**）。"""
    if profile is None:
        return {key: None for key in PROFILE_KEYS}
    return {
        "nickname": profile.nickname,
        "gender": profile.gender,
        "birth_date": profile.birth_date.strftime("%Y-%m-%d") if profile.birth_date else None,
        "age": calc_age(profile.birth_date),
        "height_cm": _out(profile.height_cm),
        "initial_weight_kg": _out(profile.initial_weight_kg),
        "blood_type": profile.blood_type,
        "medical_history": profile.medical_history,
        "allergy_history": profile.allergy_history,
        "medication_notes": profile.medication_notes,
        "updated_at": profile.updated_at.strftime("%Y-%m-%d %H:%M:%S") if profile.updated_at else None,
        # S4-2：只暴露「头像最后更新时间」；**无 `avatar_key` / 无路径 / 无可复制地址**
        "avatar_updated_at": (
            profile.avatar_updated_at.strftime("%Y-%m-%d %H:%M:%S")
            if (profile.avatar_key and profile.avatar_updated_at) else None
        ),
    }


def derived_payload(db: Session, user_id: int,
                    profile: Optional[UserProfile]) -> Dict[str, Any]:
    """``data.derived``：BMI 及其取数来源（**只陈述事实**）。"""
    record = latest_weight(db, user_id)
    weight = Decimal(record.value_1) if (record is not None and record.value_1 is not None) else None
    height = Decimal(profile.height_cm) if (profile is not None and profile.height_cm is not None) else None
    bmi = calc_bmi(weight, height)
    source = None
    if bmi is not None and record is not None:
        source = {
            "weight_kg": _out(weight),
            "height_cm": _out(height),
            "weight_recorded_at": record.recorded_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    return {"bmi": _out(bmi), "bmi_source": source}


def get_profile(db: Session, account: UserAccount) -> Dict[str, Any]:
    """P-01：读取本人档案（``user_id`` 由 Token 解析，**不接受客户端参数**）。"""
    user_id = int(account.id)
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    return {
        "profile": profile_payload(profile),
        "derived": derived_payload(db, user_id, profile),
        "target_weight": dict(TARGET_WEIGHT_GUIDANCE),
    }


def _validate(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """语义校验并计算软提示。

    返回 ``(归一化后的可写值, warnings)``；**语义非法直接抛 ``422 VALIDATION_FAILED``**
    （携带字段级 ``errors[]``，本次不写入）。
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    out: Dict[str, Any] = {}

    # ── nickname ──
    nickname = payload.get("nickname")
    if nickname is not None:
        nickname = str(nickname).strip()
        if not nickname:
            nickname = None
        elif len(nickname) > NICKNAME_MAX:
            errors.append(field_error("nickname", FieldErrorCode.INVALID_FORMAT, "昵称长度超出限制"))
    out["nickname"] = nickname

    # ── gender ──
    gender = payload.get("gender")
    if gender is not None and int(gender) not in GENDERS:
        errors.append(field_error("gender", FieldErrorCode.INVALID_FORMAT, "性别取值不在允许范围内"))
    out["gender"] = None if gender is None else int(gender)

    # ── birth_date ──
    birth_raw = payload.get("birth_date")
    birth: Optional[date] = None
    if birth_raw is not None:
        text = str(birth_raw).strip()
        if text:
            try:
                birth = datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError:
                errors.append(
                    field_error("birth_date", FieldErrorCode.INVALID_FORMAT, "日期格式应为 YYYY-MM-DD")
                )
            else:
                if birth > now_local().date():
                    errors.append(field_error("birth_date", FieldErrorCode.INVALID_FORMAT, "出生日期不得晚于今天"))
                elif birth < BIRTH_DATE_MIN:
                    errors.append(field_error("birth_date", FieldErrorCode.INVALID_FORMAT, "出生日期超出允许范围"))
    out["birth_date"] = birth

    # ── height_cm / initial_weight_kg ──
    for field, soft in (("height_cm", HEIGHT_SOFT), ("initial_weight_kg", INITIAL_WEIGHT_SOFT)):
        raw = payload.get(field)
        num = _to_decimal(raw)
        if raw is not None and num is None:
            errors.append(field_error(field, FieldErrorCode.INVALID_TYPE, "该字段必须为数字"))
            out[field] = None
            continue
        if num is not None:
            if _too_many_decimals(num):
                errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "小数位数超出允许范围"))
            elif num <= 0 or num > NUMERIC_5_1_MAX:
                errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "该数值超出可存储范围"))
            elif num < soft[0] or num > soft[1]:
                warnings.append(out_of_range(field))
        out[field] = num

    # ── blood_type ──
    blood = payload.get("blood_type")
    if blood is not None:
        blood = str(blood).strip().upper() or None
        if blood is not None and blood not in BLOOD_TYPES:
            errors.append(field_error("blood_type", FieldErrorCode.INVALID_FORMAT, "血型取值不在允许范围内"))
    out["blood_type"] = blood

    # ── 文本字段（**仅存储，不解读**） ──
    for field in TEXT_FIELDS:
        raw = payload.get(field)
        text = None if raw is None else str(raw)
        if text is not None:
            text = text.strip() or None
            if text is not None and len(text) > TEXT_MAX:
                errors.append(field_error(field, FieldErrorCode.INVALID_FORMAT, "内容长度超出限制"))
        out[field] = text

    # ── 语义非法 → 422（**硬拦截，不写入**） ──
    # 注意：必须先于 warnings 判定 —— 校验失败与软提示是**两层**，不得互相掩盖。
    if errors:
        raise validation_error(errors)

    return out, warnings


def update_profile(db: Session, account: UserAccount, payload: Dict[str, Any],
                   acknowledge: bool) -> Tuple[Optional[UserProfile], List[Dict[str, Any]]]:
    """P-02：整体替换 / UPSERT。

    返回 ``(档案行或 None, warnings)``：

    - ``warnings`` 非空且 ``acknowledge=False`` → 返回 ``(None, warnings)``，
      **本次不写入**（§3.14 软提示：等客户端带 ``acknowledge_warnings=true`` 重发）；
    - 其余情况 → 返回 ``(写后的档案行, warnings)``。
    """
    values, warnings = _validate(payload)
    if warnings and not acknowledge:
        return None, warnings

    user_id = int(account.id)
    now = now_local()
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if profile is None:
        profile = UserProfile(user_id=user_id, created_at=now, updated_at=now)
        db.add(profile)
    for key, value in values.items():
        # S4-2 加固：**白名单写入** —— 只写 `PROFILE_WRITE_FIELDS`
        # ⇒ `avatar_key` / `avatar_updated_at` 即便出现在 values 中也**永远不会**被本接口触碰。
        if key not in PROFILE_WRITE_FIELDS:
            continue
        setattr(profile, key, value)
    profile.updated_at = now
    db.commit()
    db.refresh(profile)
    return profile, warnings


def ensure_no_target_weight(payload: Dict[str, Any]) -> None:
    """**D-1 保护**：本接口**不接受** ``target_weight``（防双数据源）。"""
    if "target_weight" in payload or "target_weight_kg" in payload:
        raise validation_error(
            [field_error("target_weight", FieldErrorCode.INVALID_FORMAT,
                         "本接口不接受该字段（目标体重只能经健康目标接口写入）")]
        )


__all__ = [
    "get_profile",
    "update_profile",
    "profile_payload",
    "derived_payload",
    "calc_age",
    "calc_bmi",
    "latest_weight",
    "ensure_no_target_weight",
    "PROFILE_KEYS",
    "PROFILE_WRITE_FIELDS",
]
