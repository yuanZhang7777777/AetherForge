"""AetherForge FastAPI 入口：挂路由、静态托管、启动建表/种子。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .auth import AuthRequired, session_from, session_user_id
from .config import settings
from .db import get_db, init_db
from .models import User
from .routers import admin as admin_router
from .routers import assets as assets_router
from .routers import auth as auth_router
from .routers import clusters as clusters_router
from .routers import generations as generations_router
from .routers import projects as projects_router
from .routers import workspace as workspace_router

MEDIA_ROOT = Path(settings.media_root)
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

DIST_ROOT = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="AetherForge", version="0.1.0", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")


@app.exception_handler(AuthRequired)
async def _auth_required_handler(_request: Request, _exc: AuthRequired) -> RedirectResponse:
    return RedirectResponse(url="/login/", status_code=303)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "offline_mode": settings.offline_mode,
        "has_credentials": settings.has_credentials,
    }


app.include_router(auth_router.router)
app.include_router(workspace_router.router)
app.include_router(projects_router.router)
app.include_router(clusters_router.router)
app.include_router(assets_router.router)
app.include_router(generations_router.router)
app.include_router(admin_router.router)

def _serve_spa(request: Request, db: Session) -> FileResponse | RedirectResponse:
    """已登录 → SPA 入口；未登录 → /login/。"""
    if DIST_ROOT.is_dir():
        uid = session_user_id(session_from(request))
        if uid is not None:
            user = db.get(User, uid)
            if user is not None and user.is_active:
                return FileResponse(
                    DIST_ROOT / "index.html",
                    headers={"Cache-Control": "no-store"},
                )
    return RedirectResponse(url="/login/", status_code=302)


@app.get("/", include_in_schema=False)
def root(request: Request, db: Session = Depends(get_db)):
    """未登录访问首页 → /login/；已登录返回 SPA 入口。"""
    return _serve_spa(request, db)


if DIST_ROOT.is_dir():
    app.mount("/assets", StaticFiles(directory=str(DIST_ROOT / "assets")), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str, request: Request, db: Session = Depends(get_db)):
        """SPA 深层路由（如 /projects/xxx）刷新时回退 index.html；API 未知路径仍 404 JSON。"""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        return _serve_spa(request, db)
