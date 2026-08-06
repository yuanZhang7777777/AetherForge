"""每槽提示词：写提示词节点产出的最终英文提示词直接落 PromptVersion（lang=en），用户编辑同样直存英文。

三节点管线下不再有中文中间层与英文化编译。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Batch, Cluster, OutputSlot, PromptVersion
from .serialize import _effective_config
from .template import global_fallback_template, template_slots


def _facts(cluster: Cluster) -> list[str]:
    """商品卡补充信息优先，非空则覆盖项目级风格/要求提示词；空则用项目级兜底。

    识别自动填充的来源标记为 recognition：与项目级提示词合并（保留项目风格）；
    用户手动填写或编辑过的视为用户覆盖，只用商品卡内容。
    """
    lines: list[str] = []
    analysis = cluster.analysis_snapshot or {}
    facts = (cluster.product_facts or "").strip()
    if facts and analysis.get("product_facts_source") == "recognition":
        blocks = (cluster.batch.global_prompt, cluster.product_facts)
    elif facts:
        blocks = (cluster.product_facts,)
    else:
        blocks = (cluster.batch.global_prompt,)
    for block in blocks:
        for line in str(block).splitlines():
            line = line.strip().strip("；;，,。-•*").strip()
            if line and line not in lines:
                lines.append(line)
    return lines


def _site(cluster: Cluster) -> str:
    effective = _effective_config(cluster.batch, cluster)
    return (effective.get("market") or cluster.batch.site or "SEA").upper()


def _identity(cluster: Cluster) -> str:
    lock = (cluster.identity_lock or "").strip()
    if lock:
        return lock
    name = (cluster.product_name or cluster.name or "").strip()
    return f"主商品 {name}，部件/数量/颜色与参考图一致，禁止增减。"


def _person_policy(cluster: Cluster) -> str:
    from ..prompts import n4_person_policy

    analysis = cluster.analysis_snapshot or {}
    profile = (analysis.get("identity") or {}).get("product_profile") or {}
    return n4_person_policy(profile, _facts(cluster))


def _snapshot_site(cluster: Cluster) -> str:
    """本组设计冻结的平台/国家：prepare 启动时写入 analysis_snapshot；未冻结则回退实时值。"""
    frozen = str((cluster.analysis_snapshot or {}).get("_preparation_site") or "").strip()
    return frozen or _site(cluster)


def _structured_output(node: dict) -> dict:
    node_output = {
        "display_prompt": "",
        "localized_copy": node.get("target_language_copy") or {},
    }
    marketing_plan = node.get("marketing_plan") or {}
    if not isinstance(marketing_plan, dict):
        marketing_plan = {}
    return {
        "node_output": node_output,
        "marketing_plan": marketing_plan,
        "target_language_copy": node.get("target_language_copy") or {},
        "lang": "en",
    }


def persist_prompt_version(
    db: Session,
    cluster: Cluster,
    slot: OutputSlot,
    prompt_text: str,
    structured: dict,
    *,
    node_name: str,
    input_snapshot: dict | None = None,
    actor_id=None,
    source=None,
) -> PromptVersion:
    from datetime import datetime, timezone

    batch: Batch = cluster.batch
    effective = _effective_config(batch, cluster)
    version = PromptVersion(
        cluster_id=cluster.id,
        output_slot_id=slot.id,
        created_by_id=actor_id or batch.owner_id,
        node_name=node_name,
        template_version=(batch.output_template.version if batch.output_template else "builtin-v1"),
        provider_model="gpt-image-2",
        prompt_text=prompt_text,
        input_snapshot=input_snapshot or {},
        structured_output=structured,
        evaluation={},
        source_snapshot={
            "site": _snapshot_site(cluster),
            "size": effective.get("size") or "1:1",
            "resolution": batch.resolution or "1k",
            "origin": source or node_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(version)
    db.flush()
    return version


def persist_prompts_direct(
    db: Session,
    cluster: Cluster,
    prompts: dict[int, str],
    style_brief: str,
    *,
    actor_id=None,
) -> list[PromptVersion]:
    """把写提示词节点产出的最终英文提示词直接落 PromptVersion（lang=en）。

    prompts 为 {slot_order: 英文 prompt}；缺失槽位直接报错，避免静默产出劣质图。
    """
    template = cluster.batch.output_template or global_fallback_template(db)
    slots = [s for s in template_slots(template) if s.name != "Seller original product photo"]
    created: list[PromptVersion] = []
    for slot in slots:
        text = (prompts.get(slot.order) or "").strip()
        if not text:
            raise ValueError(f"写提示词缺失槽位 {slot.order}（{slot.name}），请重新预备生成")
        structured = _structured_output({"english_prompt": text, "target_language_copy": {}})
        created.append(
            persist_prompt_version(
                db,
                cluster,
                slot,
                text,
                structured,
                node_name="prompt_writer",
                input_snapshot={"style_brief": style_brief, "site": _snapshot_site(cluster)},
                actor_id=actor_id,
                source="n2_prompt_writer",
            )
        )
    return created


def edit_prompt_text(
    db: Session,
    cluster: Cluster,
    slot_order: int,
    prompt_text: str,
    actor_id=None,
) -> PromptVersion:
    """用户在前端编辑了某槽提示词 → 新建 PromptVersion 覆盖（approved 随之更新）。

    三节点管线直接存英文，不再进入编译链路。
    """
    template = cluster.batch.output_template or global_fallback_template(db)
    slot = next((s for s in template_slots(template) if s.order == slot_order), None)
    if slot is None:
        raise ValueError(f"槽位不存在：{slot_order}")
    return persist_prompt_version(
        db,
        cluster,
        slot,
        prompt_text.strip(),
        _structured_output({"english_prompt": prompt_text, "target_language_copy": {}}),
        node_name="user_edit",
        actor_id=actor_id,
        source="user_edit",
    )
