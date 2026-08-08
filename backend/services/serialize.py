"""序列化：把 Batch/Cluster/Generation 等 ORM 对象转成前端契约 JSON。

对齐 picturesGenerate services.py 的 serialize_project / serialize_workspace_project /
serialize_project_progress 输出。媒体 URL 走 /api/assets/{id}/media/ 与 /api/results/{id}/media/。
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session, selectinload

from ..models import Asset, Batch, Cluster, Generation, OutputTemplate, PromptVersion, ResultAsset, SkuImportItem
from .template import global_fallback_template, template_slots

_FALLBACK_NAME = "名称待确认"
_IMAGE_FILENAME_RE = re.compile(r"^[^\\/]+\.(?:jpe?g|png|webp|gif|bmp|tiff?)$", re.IGNORECASE)


def asset_media_url(asset_id) -> str:
    return f"/api/assets/{asset_id}/media/"


def result_media_url(result_id) -> str:
    return f"/api/results/{result_id}/media/"


def _project_status(status: str) -> str:
    if status in {"completed", "archived"}:
        return "completed"
    if status in {"failed", "partial"}:
        return "failed"
    if status == "queued":
        return "queued"
    if status == "running":
        return "running"
    return "draft"


def _generation_status(status: str) -> str:
    if status == "completed":
        return "completed"
    if status in {"failed", "submit_unknown", "canceled"}:
        return "failed"
    if status == "queued":
        return "queued"
    return "running"


def generation_failure_message(generation: Generation) -> str:
    if generation.status == "submit_unknown":
        return "本张出图状态不确定，请稍后刷新后重试。"
    if generation.status in {"failed", "canceled"}:
        return "本张出图未成功，可直接重试。"
    return ""


def _default_config(batch: Batch) -> dict:
    return {
        "platform": batch.platform or "",
        "market": batch.market or batch.site or "",
        "sellerTier": batch.seller_tier or "general",
        "size": batch.size or "1:1",
        "resolution": (batch.resolution or "1k").upper(),
        "globalPrompt": batch.global_prompt or "",
        "aiRecognitionEnabled": bool(batch.ai_recognition_enabled),
    }


def _effective_config(batch: Batch, cluster: Cluster) -> dict:
    defaults = _default_config(batch)
    platform = (
        cluster.platform_override
        if cluster.platform_override is not None
        else (defaults["platform"] or "global")
    )
    seller_tier = (
        cluster.seller_tier_override
        if cluster.seller_tier_override is not None
        else defaults["sellerTier"]
    )
    return {
        "platform": platform,
        "market": (
            cluster.market_override
            if cluster.market_override is not None
            else defaults["market"]
        ),
        "sellerTier": seller_tier if platform == "shopee" else "general",
        "size": defaults["size"],
        "resolution": defaults["resolution"],
        "globalPrompt": (cluster.prompt_override or "").strip() or defaults["globalPrompt"],
    }


def _strip_schema_placeholders(data) -> dict:
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if not (isinstance(v, str) and "{{" in v)}


def _public_analysis_snapshot(analysis: dict) -> dict:
    result = {}
    for key in ("identity", "fact_ledger", "rule_gate", "readiness"):
        if key in analysis:
            result[key] = analysis[key]
    if "identity" in result:
        result["identity"] = _strip_schema_placeholders(result["identity"])
    return result


def _generation_progress(outputs: list[dict]) -> dict:
    statuses = [o["status"] for o in outputs]
    return {
        "completed": sum(1 for s in statuses if s == "completed"),
        # queued 也是「在途工作」：点正式生成后立刻显示「出图中」，而不是退回预备完成
        "active": sum(1 for s in statuses if s not in {"completed", "failed"}),
        "failed": sum(1 for s in statuses if s == "failed"),
        "total": len(outputs),
    }


def _is_source_photo_slot(slot) -> bool:
    return slot.name == "Seller original product photo"


def _serialize_asset(asset: Asset) -> dict:
    item = {"id": str(asset.id), "name": asset.original_filename, "kind": asset.kind}
    if asset.kind == "image":
        item["imageUrl"] = asset_media_url(asset.id)
    return item


def _public_product_name(cluster: Cluster) -> str:
    name = (cluster.product_name or "").strip()
    if name in {_FALLBACK_NAME, ""} or "{{" in name or _IMAGE_FILENAME_RE.match(name):
        return ""
    return name


def _serialize_output(generation: Generation) -> dict:
    result = next(iter(generation.result_assets), None)
    review_status = (
        "changes_requested"
        if generation.review_status == "rejected"
        else generation.review_status
    )
    output = {
        "id": str(generation.id),
        "name": generation.output_slot.name,
        "slot": generation.output_slot.name,
        "slotId": str(generation.output_slot_id),
        "slotOrder": generation.output_slot.order,
        "attempt": generation.attempt,
        "version": generation.attempt,
        "status": _generation_status(generation.status),
        "reviewStatus": review_status,
        "prompt": generation.prompt_text,
        "promptVersionId": (
            str(generation.prompt_version_id) if generation.prompt_version_id else None
        ),
    }
    message = generation_failure_message(generation)
    if message:
        output["failureReason"] = message
    if result is not None:
        output["imageUrl"] = result_media_url(result.id)
    return output


def _serialize_output_summary(generation: Generation) -> dict:
    review_status = (
        "changes_requested"
        if generation.review_status == "rejected"
        else generation.review_status
    )
    return {
        "id": str(generation.id),
        "name": generation.output_slot.name,
        "slot": generation.output_slot.name,
        "slotId": str(generation.output_slot_id),
        "slotOrder": generation.output_slot.order,
        "attempt": generation.attempt,
        "version": generation.attempt,
        "status": _generation_status(generation.status),
        "reviewStatus": review_status,
        "promptVersionId": (
            str(generation.prompt_version_id) if generation.prompt_version_id else None
        ),
    }


def _prompt_slot_metadata(latest_prompt) -> dict:
    if latest_prompt is None:
        return {}
    structured = latest_prompt.structured_output or {}
    node_output = structured.get("node_output") if isinstance(structured, dict) else {}
    if not isinstance(node_output, dict):
        node_output = {}
    meta: dict = {}
    display = node_output.get("display_prompt") or structured.get("display_prompt")
    if display:
        meta["displayPrompt"] = str(display)
    marketing_plan = structured.get("marketing_plan")
    if isinstance(marketing_plan, dict):
        for key in ("imageGoal", "buyerQuestion", "creativeAngle", "decisionTask", "conversionGoal"):
            value = marketing_plan.get(key)
            if value:
                meta[key] = str(value)
    localized = node_output.get("localized_copy") or structured.get("localized_copy")
    if isinstance(localized, dict):
        meta["localizedCopy"] = localized
    return meta


def _prompt_slots(db: Session, cluster: Cluster, template: OutputTemplate) -> list[dict]:
    prompts = (
        db.query(PromptVersion)
        .filter_by(cluster_id=cluster.id)
        .options(selectinload(PromptVersion.output_slot))
        .all()
    )
    latest: dict = {}
    for prompt in sorted(
        prompts,
        key=lambda p: (
            p.output_slot.order if p.output_slot else 0,
            p.created_at,
            str(p.id),
        ),
    ):
        if prompt.output_slot_id:
            latest.setdefault(prompt.output_slot_id, prompt)
    result: list[dict] = []
    for slot in template_slots(template):
        latest_prompt = latest.get(slot.id)
        result.append(
            {
                "slotOrder": slot.order,
                "slot": slot.name,
                "text": latest_prompt.prompt_text if latest_prompt else "",
                "promptVersionId": str(latest_prompt.id) if latest_prompt else None,
                "readOnly": _is_source_photo_slot(slot),
                **_prompt_slot_metadata(latest_prompt),
            }
        )
    return result


def _cluster_outputs(db: Session, cluster: Cluster) -> list[dict]:
    generations = (
        db.query(Generation)
        .filter_by(cluster_id=cluster.id)
        .options(selectinload(Generation.result_assets), selectinload(Generation.output_slot))
        .order_by(Generation.output_slot_id, Generation.attempt, Generation.id)
        .all()
    )
    outputs = []
    for generation in generations:
        if _is_source_photo_slot(generation.output_slot):
            continue
        outputs.append(_serialize_output(generation))
    return outputs


def _serialize_sku(
    db: Session,
    cluster: Cluster,
    serialized_assets: dict,
    template: OutputTemplate,
    latest_imports: dict,
) -> dict:
    analysis = cluster.analysis_snapshot or {}
    cluster_assets = cluster.cluster_assets
    sku: dict = {
        "id": str(cluster.id),
        "sku": cluster.sku or "",
        "name": _public_product_name(cluster),
        "productName": _public_product_name(cluster),
        "productNameSource": analysis.get("product_name_source"),
        "storeName": cluster.store_name,
        "store_name": cluster.store_name,
        "version": cluster.version,
        "relationType": cluster.relation_type,
        "preparationStatus": cluster.preparation_status,
        "preparation": {
            "status": cluster.preparation_status,
            "stage": cluster.preparation_stage,
            "current": cluster.preparation_current,
            "total": cluster.preparation_total,
            "error": cluster.preparation_error,
        },
        "importStatus": latest_imports.get(cluster.sku, "manual") if cluster.sku else "manual",
        "assetIds": [str(item.asset_id) for item in cluster_assets],
        "assets": [
            serialized_assets[item.asset_id]
            for item in cluster_assets
            if item.asset_id in serialized_assets
        ],
        "facts": cluster.product_facts,
        "productFacts": cluster.product_facts,
        "identityLock": cluster.identity_lock,
        "brief": cluster.product_facts,
        "productStyle": cluster.prompt_override,
        "overrides": {
            "platform": cluster.platform_override,
            "market": cluster.market_override,
            "sellerTier": cluster.seller_tier_override,
        },
        "effectiveConfig": _effective_config(cluster.batch, cluster),
        "identity": _strip_schema_placeholders(analysis.get("identity") or {}),
        "factLedger": analysis.get("fact_ledger", {}),
        "marketingPlan": analysis.get("marketing_plan", {"plans": []}),
        "analysisSnapshot": _public_analysis_snapshot(analysis),
        "prompts": _prompt_slots(db, cluster, template),
        "promptSlots": _prompt_slots(db, cluster, template),
    }
    outputs = _cluster_outputs(db, cluster)
    sku["generationProgress"] = _generation_progress(outputs)
    sku["outputs"] = outputs
    return sku


def _load_clusters(db: Session, batch: Batch) -> list[Cluster]:
    from ..models import Cluster

    return (
        db.query(Cluster)
        .filter_by(batch_id=batch.id)
        .filter(Cluster.archived_at.is_(None))
        .order_by(Cluster.created_at, Cluster.id)
        .all()
    )


def serialize_project(db: Session, batch: Batch) -> dict:
    template = batch.output_template or global_fallback_template(db)
    assets = (
        db.query(Asset)
        .filter_by(batch_id=batch.id)
        .filter(Asset.archived_at.is_(None))
        .order_by(Asset.created_at, Asset.id)
        .all()
    )
    serialized_assets = {a.id: _serialize_asset(a) for a in assets}
    clusters = _load_clusters(db, batch)
    latest_imports: dict = {}
    for item in (
        db.query(SkuImportItem)
        .filter_by(batch_id=batch.id)
        .order_by(SkuImportItem.created_at.desc(), SkuImportItem.id.desc())
        .all()
    ):
        latest_imports.setdefault(item.sku, item)

    skus = [_serialize_sku(db, c, serialized_assets, template, latest_imports) for c in clusters]

    from .preflight import preflight_batch

    return {
        "id": str(batch.id),
        "name": batch.name,
        "platform": batch.platform or "",
        "market": batch.market or batch.site or "",
        "sellerTier": batch.seller_tier,
        "configurationStatus": (
            "configured" if batch.platform and (batch.market or batch.site) else "required"
        ),
        "defaultConfig": _default_config(batch),
        "template": template.name,
        "size": batch.size or "1:1",
        "resolution": (batch.resolution or "1k").upper(),
        "status": _project_status(batch.status),
        "updatedAt": _iso(batch.updated_at),
        "assets": list(serialized_assets.values()),
        "skus": skus,
        "skuImports": [],
        "templateSlots": [
            {"order": s.order, "name": s.name, "purpose": s.purpose}
            for s in template_slots(template)
        ],
        "preflight": preflight_batch(db, batch, batch.owner, template),
    }


def serialize_workspace_project(db: Session, batch: Batch, template: OutputTemplate) -> dict:
    skus = []
    clusters = _load_clusters(db, batch)
    for cluster in clusters:
        outputs = _cluster_outputs(db, cluster)
        skus.append(
            {
                "id": str(cluster.id),
                "name": _public_product_name(cluster),
                "preparationStatus": cluster.preparation_status,
                "preparation": {
                    "status": cluster.preparation_status,
                    "stage": cluster.preparation_stage,
                    "current": cluster.preparation_current,
                    "total": cluster.preparation_total,
                    "error": cluster.preparation_error,
                },
                "generationProgress": _generation_progress(outputs),
                "outputs": outputs,
            }
        )
    return {
        "id": str(batch.id),
        "name": batch.name,
        "platform": batch.platform or "",
        "market": batch.market or batch.site or "",
        "sellerTier": batch.seller_tier,
        "template": template.name,
        "size": batch.size or "1:1",
        "resolution": (batch.resolution or "1k").upper(),
        "status": _project_status(batch.status),
        "updatedAt": _iso(batch.updated_at),
        "assets": [],
        "skus": skus,
    }


def _iso(dt) -> str:
    if dt is None:
        return ""
    return dt.isoformat()


def serialize_project_progress(db: Session, batch: Batch) -> dict:
    template = batch.output_template or global_fallback_template(db)
    skus = []
    for cluster in _load_clusters(db, batch):
        outputs = _cluster_outputs(db, cluster)
        skus.append(
            {
                "id": str(cluster.id),
                "preparationStatus": cluster.preparation_status,
                "preparation": {
                    "status": cluster.preparation_status,
                    "stage": cluster.preparation_stage,
                    "current": cluster.preparation_current,
                    "total": cluster.preparation_total,
                    "error": cluster.preparation_error,
                },
                "prompts": _prompt_slots(db, cluster, template),
                "generationProgress": _generation_progress(outputs),
                "outputs": outputs,
            }
        )
    return {
        "id": str(batch.id),
        "status": _project_status(batch.status),
        "updatedAt": _iso(batch.updated_at),
        "skus": skus,
    }
