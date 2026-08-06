"""FastAPI 认证依赖：session 解析、登录用户注入、CSRF 保护。"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import CSRF_HEADER, SESSION_COOKIE, check_csrf, parse_session


class AuthRequired(Exception):
    """会话缺失/失效，转为 303 -> /login/（前端据此判定 authRequired）。"""


def session_from(request: Request) -> dict | None:
    return parse_session(request.cookies.get(SESSION_COOKIE))


def session_user_id(session: dict | None) -> uuid.UUID | None:
    """返回会话中的用户 ID，仅当是合法 UUID 时；否则（含旧版 'None' 占位）视为未登录。"""
    if not session:
        return None
    raw = session.get("user_id")
    if not raw or raw == "None":
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login/", status_code=303)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = session_from(request)
    if not session or not session.get("user_id"):
        raise AuthRequired()
    try:
        user_id = uuid.UUID(str(session["user_id"]))
    except (ValueError, TypeError):
        raise AuthRequired() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthRequired()
    return user


def csrf_protect(request: Request) -> None:
    """非 GET 请求必须携带与当前会话 cookie 匹配的 X-CSRFToken。"""
    if request.method == "GET":
        return
    if not check_csrf(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get(CSRF_HEADER),
    ):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")
