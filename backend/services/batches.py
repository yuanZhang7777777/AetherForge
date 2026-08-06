"""Batch（项目）服务：创建、设置、prepare 请求、导出选择。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..ids import safe_uuid
from ..models import Batch, Cluster, Generation, User
from ..storage import get_storage
from .assets import request_cluster_preparation
from .contract import cluster_preparation_is_current, invalidate_preparation
from .export import build_export_zip
from .generation import ACTIVE_GENERATION_STATUSES
from .serialize import _public_product_name
from .template import global_fallback_template


def create_project(db: Session, user: User, name: str) -> Batch:
    batch = Batch(owner_id=user.id, name=name.strip(), status="draft")
    db.add(batch)
    db.flush()
    return batch


def update_project_settings(
    db: Session,
    batch: Batch,
    *,
    platform: str,
    market: str,
    size: str,
    resolution: str,
    global_prompt: str,
    ai_recognition_enabled: bool,
) -> Batch:
    before = (batch.platform, batch.market, batch.site)
    if platform:
        batch.platform = platform
    if market is not None:
        batch.market = (market or "").strip().upper()
        if not batch.site:
            batch.site = batch.market
    if size:
        batch.size = size
    if resolution:
        batch.resolution = resolution
    if global_prompt is not None:
        batch.global_prompt = global_prompt
    batch.ai_recognition_enabled = ai_recognition_enabled
    if (batch.platform, batch.market, batch.site) != before:
        # 平台/国家变更 → 已生成的提示词失配，失效全部商品强制重新预备
        clusters = (
            db.query(Cluster)
            .filter_by(batch_id=batch.id)
            .filter(Cluster.archived_at.is_(None))
            .all()
        )
        for cluster in clusters:
            invalidate_preparation(cluster)
    return batch


def request_preparation_items(db: Session, batch: Batch, cluster_ids: list[str]) -> list[dict]:
    """prepare 端点逐 cluster 逻辑，返回 items。"""
    items: list[dict] = []
    for cluster_id in dict.fromkeys(cluster_ids):
        cluster = db.get(Cluster, safe_uuid(cluster_id)) if cluster_id else None
        if cluster is None or cluster.batch_id != batch.id or cluster.archived_at is not None:
            items.append(
                {
                    "cluster_id": cluster_id,
                    "status": "blocked",
                    "stage": "blocked",
                    "code": "cluster_not_found",
                }
            )
            continue
        if not batch.ai_recognition_enabled and not _public_product_name(cluster):
            items.append(
                {
                    "cluster_id": cluster_id,
                    "status": "blocked",
                    "stage": "blocked",
                    "code": "name_required",
                    "message": "请先填写商品名称",
                }
            )
            continue
        if (
            db.query(Generation.id)
            .filter(
                Generation.cluster_id == cluster.id,
                Generation.status.in_(ACTIVE_GENERATION_STATUSES),
            )
            .limit(1)
            .first()
            is not None
        ):
            items.append(
                {
                    "cluster_id": cluster_id,
                    "status": "blocked",
                    "stage": "blocked",
                    "code": "generation_active",
                    "message": "已有出图任务正在执行，完成后才能重新预备",
                }
            )
            continue
        if cluster_preparation_is_current(cluster):
            items.append(
                {"cluster_id": cluster_id, "status": "already_ready", "stage": "ready"}
            )
            continue
        if cluster.preparation_status in {"pending", "preparing"}:
            items.append(
                {
                    "cluster_id": cluster_id,
                    "status": (
                        "preparing"
                        if cluster.preparation_status == "preparing"
                        else "queued"
                    ),
                    "stage": cluster.preparation_stage,
                }
            )
            continue
        request_cluster_preparation(cluster, auto_generate=False)
        items.append(
            {"cluster_id": cluster_id, "status": "queued", "stage": cluster.preparation_stage}
        )
    return items


def export_selected_generations(db: Session, batch: Batch, requested_ids: list[str]):
    """返回 (zip_bytes, filename)。"""
    return build_export_zip(db, batch, requested_ids)
