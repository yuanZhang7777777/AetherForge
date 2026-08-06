"""工作台：/api/workspace/snapshot/。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Batch
from ..services.serialize import serialize_workspace_project
from ..services.template import global_fallback_template

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/snapshot/")
def snapshot(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batches = (
        db.query(Batch)
        .filter_by(owner_id=user.id)
        .order_by(Batch.updated_at.desc(), Batch.created_at.desc())
        .all()
    )
    template = global_fallback_template(db)
    projects = [serialize_workspace_project(db, batch, template) for batch in batches]
    return {"projects": projects, "currentUser": {"role": user.role}}
