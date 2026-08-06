"""Per-user reusable project prompt templates."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..models import User, UserPromptTemplate


def list_user_prompt_templates(db: Session, user: User) -> list[UserPromptTemplate]:
    return (
        db.query(UserPromptTemplate)
        .filter_by(user_id=user.id)
        .order_by(UserPromptTemplate.updated_at.desc(), UserPromptTemplate.created_at.desc())
        .all()
    )


def save_user_prompt_template(db: Session, user: User, name: str, content: str) -> UserPromptTemplate:
    clean_name = str(name or "").strip()[:80] or "未命名模板"
    clean_content = str(content or "").strip()
    if not clean_content:
        raise ValueError("模板内容不能为空")
    item = (
        db.query(UserPromptTemplate)
        .filter_by(user_id=user.id, name=clean_name)
        .first()
    )
    if item is None:
        item = UserPromptTemplate(user_id=user.id, name=clean_name, content=clean_content)
        db.add(item)
    else:
        item.content = clean_content
    db.flush()
    return item


def delete_user_prompt_template(db: Session, user: User, template_id: uuid.UUID) -> bool:
    item = (
        db.query(UserPromptTemplate)
        .filter_by(id=template_id, user_id=user.id)
        .first()
    )
    if item is None:
        return False
    db.delete(item)
    db.flush()
    return True
