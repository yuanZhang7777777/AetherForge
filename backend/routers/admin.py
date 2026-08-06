"""Admin 路由：prompt-nodes 只读存根（P2 补 CRUD + publish）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request, db: Session):
    user = require_user(request, db)
    if not user.is_platform_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


@router.get("/prompt-nodes/")
def list_nodes(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return {"nodes": []}
