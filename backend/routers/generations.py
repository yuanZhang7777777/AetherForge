"""Generation 路由：retry/regenerate/review/revise。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Generation
from ..schemas import ReviewInput, RevisionInput
from ..services.generation import regenerate_generation, retry_failed_generation, revise_generation
from ._helpers import coerce_uuid

router = APIRouter(prefix="/api/generations", tags=["generations"])


def _get_generation(db: Session, generation_id: str) -> Generation:
    generation = db.get(Generation, coerce_uuid(generation_id, "出图记录不存在"))
    if generation is None:
        raise HTTPException(404, "出图记录不存在")
    return generation


@router.post("/{generation_id}/retry/")
def retry(generation_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    generation = _get_generation(db, generation_id)
    try:
        new_gen = retry_failed_generation(db, generation, user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return {
        "id": str(new_gen.id),
        "attempt": new_gen.attempt,
        "status": new_gen.status,
        "review_status": new_gen.review_status,
    }


@router.post("/{generation_id}/regenerate/")
def regenerate(generation_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    generation = _get_generation(db, generation_id)
    try:
        new_gen = regenerate_generation(db, generation, user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return {
        "id": str(new_gen.id),
        "attempt": new_gen.attempt,
        "status": new_gen.status,
        "review_status": new_gen.review_status,
    }


@router.post("/{generation_id}/review/")
def review(generation_id: str, payload: ReviewInput, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    generation = _get_generation(db, generation_id)
    generation.review_status = "accepted" if payload.decision == "accept" else "rejected"
    snapshot = dict(generation.rule_snapshot or {})
    snapshot["review"] = {
        "decision": payload.decision,
        "issue_tags": payload.issue_tags,
        "description": payload.description,
        "annotations": [a.model_dump() for a in payload.annotations],
        "reviewed_by": str(user.id),
    }
    generation.rule_snapshot = snapshot
    db.commit()
    return {
        "id": str(generation.id),
        "attempt": generation.attempt,
        "status": generation.status,
        "review_status": generation.review_status,
    }


@router.post("/{generation_id}/revise/")
def revise(generation_id: str, payload: RevisionInput, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    generation = _get_generation(db, generation_id)
    try:
        new_gen = revise_generation(
            db,
            generation,
            user,
            {
                "issue_tags": payload.issue_tags,
                "description": payload.description,
                "annotations": [a.model_dump() for a in payload.annotations],
                "requested_by": str(user.id),
            },
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return {
        "id": str(new_gen.id),
        "attempt": new_gen.attempt,
        "status": new_gen.status,
        "review_status": new_gen.review_status,
    }
