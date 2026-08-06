"""preflight：批量生成前的可生成性检查。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Batch, Cluster, OutputTemplate, User
from .template import global_fallback_template, standard_hero_slot, template_slots

BATCH_GENERATION_LIMIT = 300


def _effective_template(db: Session, cluster: Cluster) -> OutputTemplate:
    return cluster.batch.output_template or global_fallback_template(db)


def preflight_batch(
    db: Session,
    batch: Batch,
    user: User,
    template: OutputTemplate | None = None,
) -> dict:
    template = template or (batch.output_template or global_fallback_template(db))
    clusters = (
        db.query(Cluster)
        .filter_by(batch_id=batch.id)
        .filter(Cluster.archived_at.is_(None))
        .all()
    )
    cluster_count = len(clusters)
    slot_count = 0
    generation_count = 0
    for cluster in clusters:
        effective = _effective_template(db, cluster)
        slots = [s for s in template_slots(effective) if s.name != "Seller original product photo"]
        slot_count = max(slot_count, len(slots))
        generation_count += len(slots)

    blocking_errors: list[str] = []
    if cluster_count == 0:
        blocking_errors.append("batch has no image clusters")
    for cluster in clusters:
        effective = _effective_template(db, cluster)
        if standard_hero_slot(effective) is None:
            blocking_errors.append("output template requires a standard product hero")
    if generation_count > BATCH_GENERATION_LIMIT:
        blocking_errors.append("batch generation limit exceeded")

    from .quota import daily_usage_remaining

    if settings.user_daily_generation_limit > 0:
        org_block, user_block = daily_usage_remaining(db, user)
        if user_block:
            blocking_errors.append("user daily quota exceeded")

    return {
        "cluster_count": cluster_count,
        "slot_count": slot_count,
        "generation_count": generation_count,
        "blocking_errors": list(dict.fromkeys(blocking_errors)),
        "template": (
            {"id": str(template.id), "name": template.name, "version": template.version}
            if template
            else None
        ),
        "rule_profile": None,
    }
