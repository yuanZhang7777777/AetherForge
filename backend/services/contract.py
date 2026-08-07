"""运行时契约指纹：判断 cluster 是否仍处于最新可复用准备状态。"""
from __future__ import annotations

import hashlib
import json

from ..models import Batch, Cluster
from .serialize import _effective_config


def preparation_fingerprint(batch: Batch, cluster: Cluster) -> str:
    cluster_assets = sorted(
        (item.asset_id, item.order, item.role) for item in cluster.cluster_assets
    )
    payload = {
        "template_id": str(batch.output_template_id or ""),
        "effective_config": _effective_config(batch, cluster),
        "identity": {
            "product_name": cluster.product_name,
            "store_name": cluster.store_name,
            "product_facts": cluster.product_facts,
            "identity_lock": cluster.identity_lock,
            "prompt_override": cluster.prompt_override,
        },
        "assets": [str(asset_id) for asset_id, _order, _role in cluster_assets],
        "relation_type": cluster.relation_type,
        "sku": cluster.sku,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cluster_preparation_is_current(cluster: Cluster) -> bool:
    if cluster.preparation_status != "ready":
        return False
    analysis = cluster.analysis_snapshot or {}
    return analysis.get("_runtime_contract_fingerprint") == preparation_fingerprint(
        cluster.batch, cluster
    )


def bump_preparation_revision(cluster: Cluster) -> None:
    analysis = dict(cluster.analysis_snapshot or {})
    analysis["_preparation_revision"] = int(analysis.get("_preparation_revision", 0)) + 1
    cluster.analysis_snapshot = analysis


def invalidate_preparation(cluster: Cluster) -> None:
    cluster.preparation_status = "draft"
    cluster.preparation_error = ""
    cluster.preparation_stage = "draft"
    cluster.preparation_current = 0
    cluster.preparation_total = 3
    cluster.auto_generate = False
    bump_preparation_revision(cluster)
