"""认证原语：PBKDF2 密码哈希、签名 session cookie、CSRF 签发/校验。

对齐旧平台契约：非 GET 请求前先 GET /api/csrf/ 取 token，请求带 X-CSRFToken；
会话失效由前端通过 303 -> /login/ 判定。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="aetherforge-session")

SESSION_COOKIE = "aetherforge_session"
CSRF_HEADER = "X-CSRFToken"

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$", 3)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def _session_payload(user_id: uuid.UUID | None, csrf: str, erp_token: str = "") -> str:
    session = {"csrf": csrf}
    if user_id is not None:
        session["user_id"] = str(user_id)
    if erp_token:
        session["erp_token"] = erp_token
    return _serializer.dumps(session)


def create_session(user_id: uuid.UUID, *, erp_token: str = "") -> tuple[str, str]:
    """返回 (cookie_value, csrf_token)。erp_token 用于 SKU 导入时查询商品目录。"""
    csrf = secrets.token_hex(24)
    return _session_payload(user_id, csrf, erp_token), csrf


def parse_session(cookie_value: str | None) -> dict | None:
    if not cookie_value:
        return None
    try:
        return _serializer.loads(cookie_value, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


def new_csrf(session: dict) -> str:
    """为已有会话轮换 CSRF token，返回新值（调用方负责写回 cookie）。"""
    csrf = secrets.token_hex(24)
    session["csrf"] = csrf
    return csrf


def check_csrf(cookie_value: str | None, header_value: str | None) -> bool:
    session = parse_session(cookie_value)
    if not session:
        return False
    expected = session.get("csrf")
    if not expected or not header_value:
        return False
    return hmac.compare_digest(expected, header_value)
