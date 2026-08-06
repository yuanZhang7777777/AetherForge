"""Cluster（商品）操作：乐观锁更新、merge/split/delete、资产删除。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Asset, Cluster, ClusterAsset
from .assets import request_cluster_preparation
from .contract import bump_preparation_revision, invalidate_preparation


class ClusterConflict(Exception):
    """expected_version 不匹配（前端 409）。"""


class ClusterNotFound(Exception):
    pass


class ClusterArchived(Exception):
    pass


def _check_version(cluster: Cluster, expected_version: int) -> None:
    if cluster.archived_at is not None:
        raise ClusterArchived("商品已归档，不能继续修改")
    if cluster.version != expected_version:
        raise ClusterConflict("商品信息刚刚更新，请刷新后再保存")


def _touch(cluster: Cluster) -> None:
    cluster.version += 1
    bump_preparation_revision(cluster)


def _requeue(cluster: Cluster) -> None:
    invalidate_preparation(cluster)
    request_cluster_preparation(cluster, auto_generate=False)


def update_cluster(
    db: Session,
    cluster: Cluster,
    expected_version: int,
    payload: dict,
    actor_id=None,
) -> Cluster:
    _check_version(cluster, expected_version)
    changed = False

    if "name" in payload and payload["name"] is not None:
        raw = str(payload["name"]).strip()
        cluster.name = raw
        if raw:
            cluster.product_name = raw[:200]
            analysis = dict(cluster.analysis_snapshot or {})
            analysis["product_name_source"] = "manual"
            cluster.analysis_snapshot = analysis
        changed = True
    if "product_facts" in payload and payload["product_facts"] is not None:
        cluster.product_facts = str(payload["product_facts"])
        analysis = dict(cluster.analysis_snapshot or {})
        analysis.pop("product_facts_source", None)
        cluster.analysis_snapshot = analysis
        changed = True
    if "relation_type" in payload and payload["relation_type"] is not None:
        cluster.relation_type = str(payload["relation_type"])
        changed = True
    if "identity_lock" in payload and payload["identity_lock"] is not None:
        cluster.identity_lock = str(payload["identity_lock"])
        changed = True
    if "prompt_override" in payload and payload["prompt_override"] is not None:
        cluster.prompt_override = str(payload["prompt_override"])
        changed = True
    if "platform_override" in payload:
        cluster.platform_override = payload["platform_override"] or None
        changed = True
    if "market_override" in payload:
        cluster.market_override = payload["market_override"] or None
        changed = True
    if "seller_tier_override" in payload:
        cluster.seller_tier_override = payload["seller_tier_override"] or None
        changed = True
    if "asset_order" in payload and payload["asset_order"]:
        _reorder_assets(db, cluster, payload["asset_order"])
        changed = True
    if "prompts" in payload and payload["prompts"]:
        from .prompt_compile import edit_prompt_text

        for item in payload["prompts"]:
            slot_order = item.get("slot_order")
            prompt = (item.get("prompt") or "").strip()
            display_prompt = item.get("display_prompt")
            if slot_order is not None and (prompt or display_prompt is not None):
                edit_prompt_text(
                    db,
                    cluster,
                    slot_order,
                    prompt,
                    display_prompt=display_prompt,
                    actor_id=actor_id,
                )
        changed = True

    if changed:
        _touch(cluster)
        # 提示词是 N2 的输出，编辑只需新建 PromptVersion（approved 随之更新），无需重跑 N2；
        # 只有影响 N2 输入的字段变更才需要重新预备，否则会把用户刚编辑的中文提示词冲掉。
        # asset_order 不重排：拖拽换序不改变身份锁/主图（N2 输入），生成时按最新顺序快照即可
        needs_requeue = any(
            key in payload
            for key in (
                "name",
                "product_facts",
                "relation_type",
                "identity_lock",
                "prompt_override",
                "platform_override",
                "market_override",
                "seller_tier_override",
            )
        )
        if cluster.preparation_status == "ready" and needs_requeue:
            _requeue(cluster)
    return cluster


def _reorder_assets(db: Session, cluster: Cluster, asset_ids: list[str]) -> None:
    positions = {str(aid): index for index, aid in enumerate(asset_ids)}
    if not positions:
        return
    for item in cluster.cluster_assets:
        if str(item.asset_id) in positions:
            item.order = positions[str(item.asset_id)] + 1


def merge_asset_into_cluster(
    db: Session,
    target: Cluster,
    asset_id: str,
    expected_version: int,
    actor_id=None,
) -> Cluster:
    _check_version(target, expected_version)
    asset = db.get(Asset, asset_id)
    if asset is None or asset.kind != "image" or asset.archived_at is not None:
        raise ClusterNotFound("素材不存在或已归档")
    source = asset.cluster_asset.cluster if asset.cluster_asset else None

    existing = next((c for c in target.cluster_assets if c.asset_id == asset.id), None)
    if existing is None:
        max_order = max((c.order for c in target.cluster_assets), default=0)
        link = asset.cluster_asset
        if link is not None and link.cluster_id != target.id:
            # cluster_assets.asset_id 唯一：跨商品移动时改挂原关联行到目标商品，
            # 不能重复 INSERT，否则触发 UniqueViolation。
            link.cluster_id = target.id
            link.role = "reference"
            link.order = max_order + 1
        else:
            db.add(
                ClusterAsset(
                    cluster_id=target.id,
                    asset_id=asset.id,
                    role="reference",
                    order=max_order + 1,
                )
            )
        # 只加参考图：不改变身份锁/主图（N2 输入），ready 状态仍有效；
        # 参考图只在正式生成时快照使用，无需重新预备生成。
        _touch(target)

    if source is not None and source.id != target.id:
        db.flush()
        remaining = (
            db.query(ClusterAsset)
            .filter(ClusterAsset.cluster_id == source.id, ClusterAsset.asset_id != asset.id)
            .count()
        )
        if remaining == 0:
            source.archived_at = source.archived_at or _now()
        _touch(source)
    return target


def split_asset_out(db: Session, asset: Asset, actor_id=None) -> Cluster:
    """把素材从当前 cluster 拆出，独立成新的 cluster。"""
    from datetime import datetime, timezone

    source = asset.cluster_asset.cluster if asset.cluster_asset else None
    if source is None:
        raise ClusterNotFound("素材不在任何商品中，无需拆分")
    if asset.kind != "image":
        raise ClusterNotFound("只有图片素材可以拆分为独立商品")

    new_cluster = Cluster(
        batch_id=source.batch_id,
        name=asset.original_filename,
        preparation_status="draft",
        preparation_stage="draft",
        preparation_total=7,
    )
    db.add(new_cluster)
    db.flush()
    db.add(ClusterAsset(cluster_id=new_cluster.id, asset_id=asset.id, role="primary", order=1))

    _touch(source)
    remaining = [c for c in source.cluster_assets if c.asset_id != asset.id]
    if not remaining:
        source.archived_at = source.archived_at or datetime.now(timezone.utc)
    else:
        if source.preparation_status == "ready":
            _requeue(source)
    return new_cluster


def delete_cluster(db: Session, cluster: Cluster, actor_id=None) -> None:
    cluster.archived_at = cluster.archived_at or _now()
    invalidate_preparation(cluster)


def delete_asset(db: Session, asset: Asset, actor_id=None) -> None:
    asset.archived_at = asset.archived_at or _now()
    if asset.cluster_asset is not None:
        cluster = asset.cluster_asset.cluster
        db.delete(asset.cluster_asset)
        db.flush()
        remaining = db.query(ClusterAsset).filter(ClusterAsset.cluster_id == cluster.id).count()
        if remaining == 0:
            cluster.archived_at = cluster.archived_at or _now()
            invalidate_preparation(cluster)
        else:
            _touch(cluster)
            if cluster.preparation_status == "ready":
                _requeue(cluster)


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
