"""OutputTemplate 辅助：全局兜底模板 + 槽位有序列表。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import OutputSlot, OutputTemplate
from ..seed import GLOBAL_TEMPLATE_KEY


def global_fallback_template(db: Session) -> OutputTemplate:
    template = db.query(OutputTemplate).filter_by(seed_key=GLOBAL_TEMPLATE_KEY).first()
    if template is None:
        template = (
            db.query(OutputTemplate).filter_by(platform="global").order_by(OutputTemplate.created_at).first()
        )
    return template


def template_slots(template: OutputTemplate) -> list[OutputSlot]:
    return sorted(template.slots, key=lambda s: (s.order, s.id))


def standard_hero_slot(template: OutputTemplate) -> OutputSlot | None:
    for slot in template_slots(template):
        if slot.name == "Standard white-background product hero":
            return slot
    for slot in template_slots(template):
        if slot.order == 1:
            return slot
    return None
