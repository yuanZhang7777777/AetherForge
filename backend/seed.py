"""种子数据：默认全局 OutputTemplate（8 槽），对齐旧平台 GLOBAL_SLOTS。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import OutputSlot, OutputTemplate

GLOBAL_TEMPLATE_KEY = "global-marketplace-baseline-template"
# 9 张电商详情页固定槽位（与写提示词节点的 9 张结构对齐）。purpose 只写通用设计意图，
# 不含任何具体商品的例子（用户明确：括号里的示例只是参考、可能是干扰项，不进系统提示词）。
GLOBAL_SLOTS = (
    (1, "Shopee high-CTR main poster",
     "Complete, accurate product hero poster with bold title, short selling points, promo badges, modules, glow, border and marketplace ad styling"),
    (2, "Key benefit", "Show one verified product selling point with a memorable visual"),
    (3, "Detail close-up", "Zoom into key details with callout lines and captions"),
    (4, "Real-life use", "Show the product being used naturally by a real person"),
    (5, "Pain point solution", "Contrast or before/after showing how the product solves a common pain point"),
    (6, "Size and material", "Show real scale and material texture"),
    (7, "Usage steps", "Step-by-step 1-4 usage demo with short captions"),
    (8, "Lifestyle", "Open lifestyle scene with props, showing the life the product enables"),
    (9, "Quality and trust", "Styling/display state emphasizing quality and craftsmanship"),
)


def seed_output_template(db: Session) -> None:
    """按 order 原地 upsert 槽位：改名/改 purpose 保留 PK，不破坏 PromptVersion/Generation 外键。

    线上已有 8 槽模板部署后自动变 9 槽（旧槽位 1–8 原地改名，新增 9）。
    """
    template = db.query(OutputTemplate).filter_by(seed_key=GLOBAL_TEMPLATE_KEY).first()
    if template is None:
        template = OutputTemplate(
            seed_key=GLOBAL_TEMPLATE_KEY,
            platform="global",
            site="",
            name="Global marketplace baseline",
            version="2026.08.05",
            status="published",
            default_size="1:1",
            default_resolution="1k",
        )
        db.add(template)
        db.flush()
    existing = {slot.order: slot for slot in template.slots}
    for order, name, purpose in GLOBAL_SLOTS:
        slot = existing.get(order)
        if slot is None:
            db.add(OutputSlot(template=template, order=order, name=name, purpose=purpose))
        elif slot.name != name or slot.purpose != purpose:
            slot.name = name
            slot.purpose = purpose
