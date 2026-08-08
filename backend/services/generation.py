"""生成编排：ensure_cluster_generations、followup 尝试、retry/regenerate。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Batch, Cluster, Generation, PromptVersion, User
from ..config import settings
from .contract import cluster_preparation_is_current
from .quota import reserve_generation_usage
from .template import global_fallback_template, standard_hero_slot, template_slots

ACTIVE_GENERATION_STATUSES = {
    "queued", "preparing", "submitting", "submitted", "processing", "archiving",
}
ACTIVE_OR_TERMINAL_RECYCLABLE = ACTIVE_GENERATION_STATUSES | {"completed"}


def approved_prompt_for_slot(db: Session, cluster: Cluster, slot) -> PromptVersion | None:
    return (
        db.query(PromptVersion)
        .filter_by(cluster_id=cluster.id, output_slot_id=slot.id)
        .order_by(PromptVersion.created_at.desc(), PromptVersion.id.desc())
        .first()
    )


def _reference_snapshot(db: Session, cluster: Cluster) -> list[str]:
    return [
        item.asset.storage_path
        for item in sorted(cluster.cluster_assets, key=lambda x: x.order)
        if item.asset.kind == "image"
    ]


def _build_generation(
    db: Session,
    cluster: Cluster,
    slot,
    prompt_version: PromptVersion,
    user: User,
    attempt: int,
) -> Generation:
    from .prompt_compile import _facts, _snapshot_site
    from .serialize import _effective_config

    effective = _effective_config(cluster.batch, cluster)
    template = cluster.batch.output_template or global_fallback_template(db)
    structured = prompt_version.structured_output or {}
    if not isinstance(structured, dict):
        structured = {}
    rule_snapshot: dict = {"prompt_lang": structured.get("lang", "en")}
    if structured.get("zh_edited"):
        # 用户改过中文生图提示词：生成时由 generation-worker 按最新中文重译 final，
        # 快照重译所需输入（身份锁/事实/当地语文案/站点）。
        rule_snapshot["zh_edited"] = True
        rule_snapshot["zh"] = str(structured.get("display_prompt") or "").strip()
        rule_snapshot["target_language_copy"] = str(
            structured.get("target_language_copy") or ""
        ).strip()
        rule_snapshot["site"] = _snapshot_site(cluster)
        rule_snapshot["identity_lock"] = (cluster.identity_lock or "").strip()
        rule_snapshot["facts"] = _facts(cluster)
    generation = Generation(
        batch_id=cluster.batch_id,
        cluster_id=cluster.id,
        output_slot_id=slot.id,
        prompt_version_id=prompt_version.id,
        created_by_id=user.id,
        attempt=attempt,
        status="queued",
        prompt_text=prompt_version.prompt_text,
        size=effective.get("size") or cluster.batch.size or "1:1",
        resolution=cluster.batch.resolution or "1k",
        reference_snapshot=_reference_snapshot(db, cluster),
        template_snapshot={
            "template_id": str(template.id),
            "name": template.name,
            "version": template.version,
            "slot_order": slot.order,
            "slot_name": slot.name,
        },
        rule_snapshot=rule_snapshot,
    )
    db.add(generation)
    db.flush()
    return generation


def _source_passthrough(db: Session, cluster: Cluster, slot, user: User, storage) -> Generation:
    """源图槽：把主参考图原样归档为已完成 Generation。"""
    from ..models import ResultAsset

    primary = next(
        (item for item in cluster.cluster_assets if item.role == "primary"), None
    )
    generation = Generation(
        batch_id=cluster.batch_id,
        cluster_id=cluster.id,
        output_slot_id=slot.id,
        created_by_id=user.id,
        attempt=1,
        status="completed",
        prompt_text="[source passthrough]",
        size="1:1",
        resolution="1k",
        reference_snapshot=[],
        template_snapshot={"slot_order": slot.order, "slot_name": slot.name},
        rule_snapshot={},
        completed_at=datetime.now(timezone.utc),
    )
    db.add(generation)
    db.flush()
    if primary is not None:
        try:
            data = storage.read(primary.asset.storage_path)
            suffix = Path(primary.asset.storage_path).suffix or ".jpg"
            result_path = (
                f"results/{cluster.batch_id}/{cluster.id}/{slot.id}/1/{uuid.uuid4().hex}{suffix}"
            )
            storage.save(result_path, data)
            db.add(
                ResultAsset(
                    generation_id=generation.id,
                    storage_path=result_path,
                    source_url="",
                    sha256=hashlib.sha256(data).hexdigest(),
                    file_size=len(data),
                    width=primary.asset.width,
                    height=primary.asset.height,
                )
            )
        except Exception:
            pass
    return generation


def _latest_attempt(db: Session, cluster_id, slot_id) -> int:
    value = (
        db.query(Generation.attempt)
        .filter_by(cluster_id=cluster_id, output_slot_id=slot_id)
        .order_by(Generation.attempt.desc())
        .first()
    )
    return value[0] if value else 0


def ensure_cluster_generations(
    db: Session,
    cluster: Cluster,
    user: User,
    slot_orders: list[int] | None = None,
    force_new: bool = False,
):
    """为 cluster 的每个可生成槽位创建 QUEUED Generation；复用仍有效的已有 Generation。"""
    from ..storage import get_storage

    batch = cluster.batch
    template = batch.output_template or global_fallback_template(db)
    slots = [s for s in template_slots(template) if s.name != "Seller original product photo"]
    if not slots:
        raise ValueError("output template requires a standard product hero")
    hero = standard_hero_slot(template)
    requested = {int(order) for order in (slot_orders or [])}
    if requested and hero is not None:
        requested.add(hero.order)

    existing = (
        db.query(Generation)
        .filter_by(cluster_id=cluster.id)
        .order_by(Generation.attempt.desc(), Generation.id.desc())
        .all()
    )
    kept_by_slot: dict = {}
    for generation in existing:
        slot_id = generation.output_slot_id
        if slot_id in kept_by_slot:
            continue
        if generation.status not in ACTIVE_OR_TERMINAL_RECYCLABLE:
            continue
        if generation.status == "completed":
            approved = approved_prompt_for_slot(db, cluster, generation.output_slot)
            if approved is None or generation.prompt_version_id != approved.id:
                continue
        kept_by_slot[slot_id] = generation

    created_ids: list[str] = []
    for slot in slots:
        if requested and slot.order not in requested:
            continue
        if slot.name == "Seller original product photo":
            if slot.id not in kept_by_slot:
                _source_passthrough(db, cluster, slot, user, get_storage())
            continue
        kept = kept_by_slot.get(slot.id)
        if kept is not None and not force_new:
            continue
        prompt_version = approved_prompt_for_slot(db, cluster, slot)
        if prompt_version is None:
            raise ValueError(f"prompt not ready for slot {slot.order}")
        attempt = _latest_attempt(db, cluster.id, slot.id) + 1
        generation = _build_generation(db, cluster, slot, prompt_version, user, attempt)
        created_ids.append(str(generation.id))

    if created_ids:
        reserve_generation_usage(db, user, len(created_ids))
        batch.status = "queued"
    return created_ids


def _create_followup_attempt(
    db: Session,
    source: Generation,
    user: User,
    prompt_version: PromptVersion | None = None,
) -> Generation:
    batch = source.batch
    cluster = source.cluster
    if source.status not in {"completed", "failed", "canceled", "submit_unknown"}:
        raise ValueError("generation is not in a terminal state")
    siblings = (
        db.query(Generation)
        .filter_by(cluster_id=cluster.id, output_slot_id=source.output_slot_id)
        .order_by(Generation.attempt.desc(), Generation.id.desc())
        .all()
    )
    if siblings and any(s.status in ACTIVE_GENERATION_STATUSES for s in siblings):
        raise ValueError("A newer generation attempt already exists")
    if siblings and siblings[0].id != source.id:
        raise ValueError("A newer generation attempt already exists")
    attempt = max(s.attempt for s in siblings) + 1
    pv = prompt_version or source.prompt_version
    if pv is None:
        pv = approved_prompt_for_slot(db, cluster, source.output_slot)
    if pv is None:
        raise ValueError("no approved prompt for slot")
    generation = Generation(
        batch_id=batch.id,
        cluster_id=cluster.id,
        output_slot_id=source.output_slot_id,
        prompt_version_id=pv.id,
        created_by_id=user.id,
        attempt=attempt,
        status="queued",
        prompt_text=pv.prompt_text,
        size=source.size or "1:1",
        resolution=source.resolution or "1k",
        reference_snapshot=source.reference_snapshot,
        template_snapshot=source.template_snapshot,
        rule_snapshot={**source.rule_snapshot, "english_compiled": False},
    )
    db.add(generation)
    db.flush()
    reserve_generation_usage(db, user, 1)
    batch.status = "queued"
    return generation


def retry_failed_generation(db: Session, generation: Generation, user: User) -> Generation:
    if generation.status not in {"failed", "canceled"}:
        raise ValueError("只有失败或取消的出图可以重试")
    return _create_followup_attempt(db, generation, user)


def regenerate_generation(db: Session, generation: Generation, user: User) -> Generation:
    return _create_followup_attempt(db, generation, user)


def revise_generation(db: Session, generation: Generation, user: User, feedback: dict) -> Generation:
    new_gen = _create_followup_attempt(db, generation, user)
    previous_paths = [asset.storage_path for asset in generation.result_assets if asset.storage_path]
    if previous_paths:
        new_gen.reference_snapshot = list(dict.fromkeys(previous_paths))
    snapshot = dict(new_gen.rule_snapshot or {})
    snapshot["revision_feedback"] = feedback
    new_gen.rule_snapshot = snapshot
    db.flush()
    return new_gen


def pause_project_work(db: Session, batch: Batch, cluster_ids, generation_ids):
    from ..ids import safe_uuid
    from ..models import Cluster

    clusters_out: list[dict] = []
    for cluster_id in dict.fromkeys(cluster_ids):
        cluster = db.get(Cluster, safe_uuid(cluster_id)) if cluster_id else None
        if cluster is None or cluster.batch_id != batch.id or cluster.archived_at is not None:
            clusters_out.append({"cluster_id": cluster_id, "status": "not_found"})
            continue
        if cluster.preparation_status in {"pending", "preparing"}:
            from .contract import invalidate_preparation

            invalidate_preparation(cluster)
            clusters_out.append({"cluster_id": cluster_id, "status": "paused"})
        else:
            clusters_out.append({"cluster_id": cluster_id, "status": "idle"})

    generations_out: list[dict] = []
    query = db.query(Generation).filter(Generation.batch_id == batch.id)
    ids = [safe_uuid(i) for i in dict.fromkeys(cluster_ids) if i]
    ids = [i for i in ids if i is not None]
    if ids:
        query = query.filter(Generation.cluster_id.in_(ids))
    gen_ids = [safe_uuid(g) for g in generation_ids if g]
    gen_ids = [g for g in gen_ids if g is not None]
    if gen_ids:
        query = query.filter(Generation.id.in_(gen_ids))
    for generation in query.all():
        if generation.status in ACTIVE_GENERATION_STATUSES:
            generation.status = "canceled"
            generation.failure_reason = "Paused by operator"
            generations_out.append({"generation_id": str(generation.id), "status": "canceled"})
    if generations_out:
        batch.recompute_status()
    return {"clusters": clusters_out, "generations": generations_out}
