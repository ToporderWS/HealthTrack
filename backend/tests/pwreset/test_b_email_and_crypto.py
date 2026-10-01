# -*- coding: utf-8 -*-
"""B1-B：邮箱规范化 ＋ 密码学原语（**纯函数，不触库**）。

对应需求方 B1 §三「邮箱规范化必须明确：trim / 大小写 / canonical storage / uniqueness」、
§四「验证码不得明文入库（HMAC-SHA256(pepper, user_id:purpose:code)）」、
§五「reset token 使用密码学安全随机值、只存 hash」。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import string

import pytest

from app.core.password_reset import (
    ALLOWED_PURPOSES,
    CODE_LENGTH,
    CODE_MAX_ATTEMPTS,
    CODE_MAX_ACTIVE_PER_PURPOSE,
    EMAIL_MAX_LEN,
    PURPOSE_EMAIL_BIND,
    PURPOSE_PASSWORD_RESET,
    RESET_TOKEN_BYTES,
    RESEND_COOLDOWN_SECONDS,
    RESET_TOKEN_TTL_MINUTES,
    CODE_TTL_MINUTES,
    generate_reset_token,
    generate_verification_code,
    hash_reset_token,
    hash_verification_code,
    is_valid_email,
    normalize_email,
    require_pepper,
    require_purpose,
    verify_verification_code,
)

#: 测试用 pepper（**伪造值**，仅用于本文件；绝非任何环境的生产密钥）
PEPPER = "p" * 32


# ══════════════════════════════════════════════════════════════════
# 1. 邮箱规范化
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "raw,expected",
    (
        ("  A@B.COM  ", "a@b.com"),
        ("\ta@b.com\n", "a@b.com"),
        ("a@b.com", "a@b.com"),
        ("A@B.com", "a@b.com"),
        ("someone@example.com", "someone@example.com"),
        ("", ""),
        (None, ""),
    ),
)
def test_normalize_email(raw, expected: str) -> None:
    assert normalize_email(raw) == expected


def test_normalize_email_is_idempotent() -> None:
    once = normalize_email("  Mixed@CaSe.ORG ")
    assert normalize_email(once) == once


@pytest.mark.parametrize(
    "raw",
    (
        "a.b+tag@example.com",   # **必须保留 local-part 的点与 +tag**
        "first.last@example.com",
        "user+1@example.com",
    ),
)
def test_no_special_case_folding(raw: str) -> None:
    """**禁止**去点 / 去 ``+tag`` —— 它们会把两个不同用户的地址折叠成同一规范形。"""
    assert normalize_email(raw) == raw


def test_normalize_preserves_accent_and_non_ascii() -> None:
    assert normalize_email("  Café@Ex.COM ") == "café@ex.com"


@pytest.mark.parametrize(
    "value,ok",
    (
        ("a@b.com", True),
        ("a.b+tag@sub.example.co", True),
        ("café@ex.com", True),
        ("bad@@x.com", False),
        ("no-at-sign", False),
        ("sp ace@x.com", False),
        ("a@b", False),
        ("a@-bad.com", False),
        ("", False),
        ("a@" + "x" * EMAIL_MAX_LEN + ".com", False),
    ),
)
def test_is_valid_email(value: str, ok: bool) -> None:
    assert is_valid_email(value) is ok


# ══════════════════════════════════════════════════════════════════
# 2. pepper / purpose 装载（fail-fast）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad", (None, "", "   ", "CHANGE_ME_TO_RANDOM_64_HEX", "change_me_x"))
def test_require_pepper_fails_fast(bad) -> None:
    """缺失 / 占位符一律抛错，**绝不静默落回默认值**。"""
    with pytest.raises(RuntimeError):
        require_pepper(bad)


def test_require_pepper_returns_trimmed() -> None:
    assert require_pepper("  " + PEPPER + "  ") == PEPPER


@pytest.mark.parametrize("bad", ("", None, "reset", "PASSWORD_RESET", "email_verify", "code"))
def test_require_purpose_rejects_unknown(bad) -> None:
    with pytest.raises(ValueError):
        require_purpose(bad)


def test_allowed_purposes_are_frozen() -> None:
    assert ALLOWED_PURPOSES == ("password_reset", "email_bind")
    assert PURPOSE_PASSWORD_RESET == "password_reset"
    assert PURPOSE_EMAIL_BIND == "email_bind"


# ══════════════════════════════════════════════════════════════════
# 3. 验证码 HMAC
# ══════════════════════════════════════════════════════════════════
def _hmac_sha256_by_definition(key: bytes, msg: bytes) -> str:
    """**按 HMAC 定义**（RFC 2104）实现的独立参照：``H((K⊕opad)‖H((K⊕ipad)‖m))``。

    用途：让 KAT 向量的正确性**不依赖**被测实现（也不依赖 ``hmac`` 库），
    从而避免「期望值取自被测对象自身」的判据缺陷（铁律⑨）。
    """
    block = 64
    if len(key) > block:
        key = hashlib.sha256(key).digest()
    key = key.ljust(block, b"\x00")
    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)
    inner = hashlib.sha256(ipad + msg).digest()
    return hashlib.sha256(opad + inner).hexdigest()


#: 已知答案向量（KAT）：pepper=32×"p"，user_id=7，purpose=password_reset，code=123456
KAT_HEX = "983c3f383721eea4719450148b202b6a297cf9d9e3ab02a69220a2cadc50297b"


def test_kat_matches_rfc2104_definition() -> None:
    """先自证 KAT 向量本身正确（独立于被测实现）。"""
    assert _hmac_sha256_by_definition(
        PEPPER.encode(), b"7:password_reset:123456"
    ) == KAT_HEX
    assert hmac.new(
        PEPPER.encode(), b"7:password_reset:123456", hashlib.sha256
    ).hexdigest() == KAT_HEX


def test_hash_verification_code_known_answer() -> None:
    assert hash_verification_code(PEPPER, 7, PURPOSE_PASSWORD_RESET, "123456") == KAT_HEX


def test_hash_is_hex64_and_deterministic() -> None:
    a = hash_verification_code(PEPPER, 7, PURPOSE_PASSWORD_RESET, "123456")
    b = hash_verification_code(PEPPER, 7, PURPOSE_PASSWORD_RESET, "123456")
    assert a == b
    assert len(a) == 64 and re.fullmatch(r"[0-9a-f]{64}", a)


def test_hash_never_contains_plaintext_code() -> None:
    code = "654321"
    digest = hash_verification_code(PEPPER, 11, PURPOSE_PASSWORD_RESET, code)
    assert code not in digest


@pytest.mark.parametrize(
    "pepper,uid,purpose,code",
    (
        ("q" * 32, 7, PURPOSE_PASSWORD_RESET, "123456"),   # 换 pepper
        (PEPPER, 8, PURPOSE_PASSWORD_RESET, "123456"),     # 换 user_id
        (PEPPER, 7, PURPOSE_EMAIL_BIND, "123456"),         # 换 purpose
        (PEPPER, 7, PURPOSE_PASSWORD_RESET, "123457"),     # 换 code
    ),
)
def test_hash_binds_every_component(pepper, uid, purpose, code) -> None:
    """pepper / user_id / purpose / code **四者任一变化都必须改变摘要**。

    ``user_id`` 绑定 ⇒ 同一串 6 位数字在两账号间不可通用；
    ``purpose`` 绑定 ⇒ **防跨用途复用**（``email_bind`` 的码不得通过 ``password_reset``）。
    """
    assert hash_verification_code(pepper, uid, purpose, code) != KAT_HEX


def test_verify_roundtrip_and_mismatch() -> None:
    digest = hash_verification_code(PEPPER, 7, PURPOSE_PASSWORD_RESET, "123456")
    assert verify_verification_code(PEPPER, 7, PURPOSE_PASSWORD_RESET, "123456", digest)
    assert not verify_verification_code(PEPPER, 7, PURPOSE_PASSWORD_RESET, "123457", digest)
    assert not verify_verification_code(PEPPER, 8, PURPOSE_PASSWORD_RESET, "123456", digest)
    assert not verify_verification_code(PEPPER, 7, PURPOSE_EMAIL_BIND, "123456", digest)


@pytest.mark.parametrize(
    "pepper,uid,purpose,code,expected",
    (
        (PEPPER, 7, PURPOSE_PASSWORD_RESET, "", KAT_HEX),   # 空码
        (PEPPER, 7, PURPOSE_PASSWORD_RESET, "123456", None),  # 无摘要
        (None, 7, PURPOSE_PASSWORD_RESET, "123456", KAT_HEX),  # 无 pepper
        (PEPPER, 7, "bogus", "123456", KAT_HEX),            # 非法 purpose
    ),
)
def test_verify_returns_false_on_bad_input(pepper, uid, purpose, code, expected) -> None:
    """任何异常路径一律 ``False``（**不抛异常、不泄露内部细节**）。"""
    assert verify_verification_code(pepper, uid, purpose, code, expected) is False


# ══════════════════════════════════════════════════════════════════
# 4. 验证码生成
# ══════════════════════════════════════════════════════════════════
def test_generate_verification_code_shape() -> None:
    for _ in range(200):
        code = generate_verification_code()
        assert len(code) == CODE_LENGTH
        assert code.isdigit()
        assert 0 <= int(code) < 10 ** CODE_LENGTH


def test_generate_verification_code_is_random() -> None:
    """200 次抽样至少出现 50 个不同值（排除「常量 / 弱随机」实现）。"""
    assert len({generate_verification_code() for _ in range(200)}) >= 50


# ══════════════════════════════════════════════════════════════════
# 5. 一次性重置凭证
# ══════════════════════════════════════════════════════════════════
def test_reset_token_shape_and_entropy() -> None:
    alphabet = set(string.ascii_letters + string.digits + "-_")
    tokens = [generate_reset_token() for _ in range(200)]
    assert len(set(tokens)) == 200, "出现重复 token ⇒ 随机源不可用"
    for token in tokens:
        assert set(token) <= alphabet, "token 含非 URL-safe 字符"
        assert len(token) == 64, f"48 字节 base64url 应为 64 字符，实为 {len(token)}"


def test_hash_reset_token_matches_sha256_definition() -> None:
    raw = "known-reset-token-for-test"
    assert hash_reset_token(raw) == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert len(hash_reset_token(raw)) == 64


def test_hash_reset_token_never_contains_raw() -> None:
    raw = generate_reset_token()
    digest = hash_reset_token(raw)
    assert raw not in digest
    assert digest != raw


def test_reset_token_is_not_an_access_token() -> None:
    """``SR-5``：凭证**不是 JWT**、不带任何三段结构、不可被解析为登录态。"""
    token = generate_reset_token()
    assert token.count(".") == 0, "疑似 JWT 形态"


# ══════════════════════════════════════════════════════════════════
# 6. 策略常量冻结（**值变更必须与判据同批**，铁律⑬）
# ══════════════════════════════════════════════════════════════════
def test_policy_constants_frozen() -> None:
    assert CODE_TTL_MINUTES == 15
    assert RESET_TOKEN_TTL_MINUTES == 15
    assert CODE_MAX_ATTEMPTS == 5
    assert CODE_MAX_ACTIVE_PER_PURPOSE == 1
    assert RESEND_COOLDOWN_SECONDS == 60   # B0 冻结：[重发] 60s 倒计时
    assert RESET_TOKEN_BYTES == 48
    assert EMAIL_MAX_LEN == 254
