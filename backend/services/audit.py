"""审计事件写入。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent


def audit(
    db: Session,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str,
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=str(object_id or ""),
        extra=metadata or {},
    )
    db.add(event)
    return event
