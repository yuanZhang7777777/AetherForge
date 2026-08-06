"""User-owned prompt template API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..ids import safe_uuid
from ..schemas import PromptTemplateCreate
from ..services.prompt_templates import (
    delete_user_prompt_template,
    list_user_prompt_templates,
    save_user_prompt_template,
)

router = APIRouter(prefix="/api/prompt-templates", tags=["prompt-templates"])


def _serialize(item) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "content": item.content,
        "updatedAt": item.updated_at.isoformat(),
    }


@router.get("/")
def list_templates(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return {"templates": [_serialize(item) for item in list_user_prompt_templates(db, user)]}


@router.post("/", status_code=201)
def save_template(payload: PromptTemplateCreate, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    try:
        item = save_user_prompt_template(db, user, payload.name, payload.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _serialize(item)


@router.delete("/{template_id}/")
def delete_template(template_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    template_pk = safe_uuid(template_id)
    if template_pk is None or not delete_user_prompt_template(db, user, template_pk):
        raise HTTPException(404, "模板不存在")
    db.commit()
    return {"status": "deleted"}
