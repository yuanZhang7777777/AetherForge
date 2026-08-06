"""认证路由：/login /logout /api/csrf/ /api/current-user/。"""
from __future__ import annotations

import html
import logging
from urllib.parse import quote

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
    parse_session,
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
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#e2e8f0;background-color:#0f172a;background-image:radial-gradient(60rem 40rem at 115% -10%,rgba(99,102,241,.35),transparent 60%),radial-gradient(50rem 35rem at -15% 115%,rgba(56,189,248,.22),transparent 55%),linear-gradient(160deg,#0f172a 0%,#1e1b4b 55%,#0f172a 100%);background-attachment:fixed}}
.card{{position:relative;width:min(400px,calc(100vw - 2rem));padding:40px 36px;border-radius:24px;box-sizing:border-box;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);box-shadow:0 30px 80px -20px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}}
.brand{{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:700;letter-spacing:-.01em}}
.brand-tile{{display:grid;place-items:center;width:36px;height:36px;border-radius:10px;font-size:12px;font-weight:700;color:#fff;background:linear-gradient(135deg,#4f46e5,#7c3aed);box-shadow:0 8px 20px -6px rgba(99,102,241,.7)}}
.eyebrow{{display:inline-flex;margin-top:22px;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:#c7d2fe;background:rgba(99,102,241,.18);border:1px solid rgba(129,140,248,.25)}}
h1{{margin:10px 0 6px;font-size:26px;font-weight:700;letter-spacing:-.02em;color:#f8fafc}}
.sub{{margin:0;font-size:13px;color:#94a3b8;line-height:1.6}}
form{{margin-top:28px}}
label{{display:block;margin:16px 0 6px;font-size:12px;color:#cbd5e1}}
input{{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:12px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.08);color:#f8fafc;font-size:14px;outline:none;transition:border-color .15s,box-shadow .15s}}
input::placeholder{{color:#64748b}}
input:focus{{border-color:rgba(129,140,248,.7);box-shadow:0 0 0 3px rgba(99,102,241,.3)}}
button{{width:100%;margin-top:26px;padding:13px;border:0;border-radius:14px;font-size:14px;font-weight:600;color:#fff;cursor:pointer;background-image:linear-gradient(135deg,#4f46e5,#7c3aed);box-shadow:0 14px 30px -10px rgba(99,102,241,.7);transition:transform .15s,box-shadow .15s,filter .15s}}
button:hover{{transform:translateY(-1px);filter:brightness(1.07)}}
.error{{margin-top:16px;padding:10px 12px;border-radius:10px;font-size:13px;color:#fecaca;background:rgba(225,29,72,.16);border:1px solid rgba(244,63,94,.3)}}
</style></head>
<body><form class="card" method="post" action="/login/">
<div class="brand"><span class="brand-tile">AF</span>AetherForge</div>
<div class="eyebrow">员工登录</div>
<h1>欢迎回来</h1>
<p class="sub">使用 ERP 账号登录，进入 AetherForge 出图工作台。</p>
<input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
<label for="username">ERP 用户名</label><input id="username" name="username" autocomplete="username" placeholder="请输入 ERP 用户名" required>
<label for="password">ERP 密码</label><input id="password" name="password" type="password" autocomplete="current-password" placeholder="请输入密码" required>
<button type="submit">登录</button>
{error}
</form></body></html>"""


def _app_redirect() -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html><head><meta http-equiv="refresh" content="0;url=/"></head><body></body></html>'
    )


def _login_page(csrf: str, error: str = "") -> HTMLResponse:
    return HTMLResponse(_LOGIN_PAGE.format(csrf=csrf, error=error))


def _no_cache(response: HTMLResponse) -> HTMLResponse:
    """登录页禁止缓存：缓存会让页面里的 csrf 与 cookie 脱节，造成“会话校验失败”。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _login_session_pair(request: Request) -> tuple[str, str]:
    """取与浏览器 cookie 一致的 (cookie_value, csrf)：复用现有有效会话，使页面 token 与 cookie 永不脱节；否则新建匿名会话。"""
    cookie_value = request.cookies.get(SESSION_COOKIE)
    session = parse_session(cookie_value)
    if session is not None:
        csrf = str(session.get("csrf") or "")
        if csrf:
            return cookie_value, csrf
    return create_session(None)


def _fresh_login_page(request: Request, error: str = "") -> HTMLResponse:
    """渲染登录页：页面 csrf 与浏览器会话 cookie 一一对应，刷新/多标签/出错重试都不会脱节。"""
    cookie_value, csrf = _login_session_pair(request)
    response = _login_page(csrf, error=error)
    _set_session_cookie(response, cookie_value)
    return _no_cache(response)


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


_LOGIN_ERRORS = {
    "session": "会话校验失败，请刷新重试",
    "invalid": "无效请求",
}


def _login_error_page(message: str) -> RedirectResponse:
    """PRG：POST 失败一律 303 → GET /login/?error=...，刷新不会触发浏览器「重复提交」确认。"""
    return RedirectResponse(url=f"/login/?error={quote(message)}", status_code=303)


@router.get("/login/", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    from ..auth import session_from, session_user_id

    uid = session_user_id(session_from(request))
    if uid is not None:
        user = db.get(User, uid)
        if user is not None and user.is_active:
            return _app_redirect()
    raw = request.query_params.get("error", "")
    message = _LOGIN_ERRORS.get(raw, raw) if raw else ""
    error = f"<div class='error'>{html.escape(message)}</div>" if message else ""
    return _fresh_login_page(request, error=error)


def _authenticate_login(request: Request, db: Session, username: str, password: str) -> RedirectResponse:
    """校验 ERP/本地凭据并签发会话；成功 303 → /，失败 303 → /login/?error=...（PRG，刷新无重复提交提示）。"""
    erp_token = ""
    if settings.erp_login_url:
        try:
            user, erp_token = authenticate_erp_user(db, username, password)
        except ErpAuthError as exc:
            return _login_error_page(str(exc))
    else:
        user = db.query(User).filter_by(username=username).first()
        if user is None or not verify_password(password, user.password_hash):
            return _login_error_page("用户名或密码错误")
    if not user.is_active:
        return _login_error_page("账号已停用")
    payload, _ = create_session(user.id, erp_token=erp_token)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, payload)
    return response


@router.post("/login/", response_class=HTMLResponse, include_in_schema=False)
async def login(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    from ..auth import session_from

    try:
        form = await request.form()
    except Exception:
        return _login_error_page("invalid")
    csrf = (form.get("csrfmiddlewaretoken") or "").strip()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    cookie_value = request.cookies.get(SESSION_COOKIE)
    session = parse_session(cookie_value)
    if session is None and csrf:
        # 无有效会话 cookie：csrf 是 GET /login/ 生成、仅内嵌当前表单，攻击者无法注入，
        # 接受非空 token 兜底，覆盖浏览器未保存匿名 cookie 的登录场景。有 cookie 仍严格比对。
        return _authenticate_login(request, db, username, password)
    if not check_csrf(cookie_value, csrf):
        logging.getLogger("aetherforge.auth").warning(
            "login csrf rejected: has_cookie=%s session=%s expected_len=%s submitted_len=%s",
            cookie_value is not None,
            session is not None,
            len((session or {}).get("csrf") or ""),
            len(csrf),
        )
        return _login_error_page("session")
    return _authenticate_login(request, db, username, password)


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
