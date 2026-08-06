"""认证路由：/login /logout /api/csrf/ /api/current-user/。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import AuthRequired, require_user
from ..config import settings
from ..db import get_db
from ..models import User
from ..security import (
    CSRF_HEADER,
    SESSION_COOKIE,
    check_csrf,
    create_session,
    verify_password,
)
from ..services.erp_auth import ErpAuthError, authenticate_erp_user

router = APIRouter()


def _set_session_cookie(response, payload: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        payload,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )


_LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>登录 - AetherForge</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1e293b;padding:40px;border-radius:12px;width:320px;box-shadow:0 10px 30px rgba(0,0,0,.4)}}
h1{{font-size:18px;margin:0 0 24px}}
label{{display:block;font-size:13px;margin:14px 0 6px;color:#94a3b8}}
input{{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0}}
button{{width:100%;margin-top:22px;padding:11px;border:0;border-radius:8px;background:#3b82f6;color:#fff;font-weight:600;cursor:pointer}}
.error{{color:#f87171;font-size:13px;margin-top:14px}}
</style></head>
<body><form class="card" method="post" action="/login/">
<h1>员工登录 - AetherForge</h1>
<input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
<label for="username">ERP 用户名</label><input id="username" name="username" autocomplete="username" required>
<label for="password">ERP 密码</label><input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">登录</button>
{error}
</form></body></html>"""


def _app_redirect() -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html><head><meta http-equiv="refresh" content="0;url=/"></head><body></body></html>'
    )


def _login_page(csrf: str, error: str = "") -> HTMLResponse:
    return HTMLResponse(_LOGIN_PAGE.format(csrf=csrf, error=error))


@router.get("/api/csrf/", include_in_schema=False)
def csrf_token(request: Request) -> JSONResponse:
    from ..auth import session_from

    session = session_from(request)
    if session is not None:
        return JSONResponse({"csrf_token": session["csrf"]})
    cookie_value, csrf = create_session(None)
    response = JSONResponse({"csrf_token": csrf})
    _set_session_cookie(response, cookie_value)
    return response


@router.get("/login/", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    from ..auth import session_from, session_user_id

    uid = session_user_id(session_from(request))
    if uid is not None:
        user = db.get(User, uid)
        if user is not None and user.is_active:
            return _app_redirect()
        # 会话引用的用户已不存在/停用：覆写为匿名会话展示登录页，避免死循环
        cookie_value, csrf = create_session(None)
        response = _login_page(csrf)
        _set_session_cookie(response, cookie_value)
        return response
    cookie_value, csrf = create_session(None)
    response = _login_page(csrf)
    _set_session_cookie(response, cookie_value)
    return response


@router.post("/login/", response_class=HTMLResponse, include_in_schema=False)
async def login(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    from ..auth import session_from

    try:
        form = await request.form()
    except Exception:
        return _login_page("", error="<div class='error'>无效请求</div>")
    csrf = (form.get("csrfmiddlewaretoken") or "").strip()
    if not check_csrf(request.cookies.get(SESSION_COOKIE), csrf):
        return _login_page("", error="<div class='error'>会话校验失败，请刷新重试</div>")
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    if settings.erp_login_url:
        try:
            user, _token = authenticate_erp_user(db, username, password)
        except ErpAuthError as exc:
            return _login_page("", error=f"<div class='error'>{exc}</div>")
    else:
        user = db.query(User).filter_by(username=username).first()
        if user is None or not verify_password(password, user.password_hash):
            return _login_page("", error="<div class='error'>用户名或密码错误</div>")
    if not user.is_active:
        return _login_page("", error="<div class='error'>账号已停用</div>")
    payload, _ = create_session(user.id)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, payload)
    return response


@router.post("/logout/", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    if not check_csrf(
        request.cookies.get(SESSION_COOKIE),
        request.headers.get(CSRF_HEADER),
    ):
        raise AuthRequired()
    response = RedirectResponse(url="/login/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/api/current-user/", include_in_schema=False)
def current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    user = require_user(request, db)
    return {"role": user.role}
