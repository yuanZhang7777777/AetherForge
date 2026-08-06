"""单个 prepare 任务：独立 session，处理过期 revision 竞争。"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Cluster
from ..services.generation import ensure_cluster_generations
from ..services.prepare import run_cluster_preparation

log = logging.getLogger("aetherforge.prompt_worker")


def run_prepare_job(cluster_id: str, claimed_revision: int) -> None:
    with SessionLocal() as db:
        cluster = db.get(Cluster, cluster_id)
        if cluster is None or cluster.preparation_status != "preparing":
            return
        ok = run_cluster_preparation(db, cluster)
        current_revision = int((cluster.analysis_snapshot or {}).get("_preparation_revision", 0))
        edited_during_run = current_revision != claimed_revision
        if edited_during_run:
            # 处理期间被编辑（无论成败）→ 重新排队，让最新配置重跑
            cluster.preparation_status = "pending"
            cluster.preparation_stage = "queued"
            cluster.preparation_error = "商品信息在处理期间更新，已重新排队"
            db.commit()
            return
        if not ok:
            # 真失败：必须落库 failed（此前遗漏——失败状态被 session.close 回滚，卡片永远卡在 preparing，
            # 且 claim 循环只认 pending，无法重试）
            db.commit()
            return
        db.commit()  # 先落库 ready，再独立处理自动出图
        if cluster.auto_generate:
            _auto_generate(db, cluster)


def _auto_generate(db: Session, cluster: Cluster) -> None:
    """自动出图：预备完成后直接创建 QUEUED Generation，交给 generation-worker 出图。

    独立事务：失败（配额不足/提示词缺失）时回滚，不绕过配额，也不破坏已落库的 ready。
    """
    owner = cluster.batch.owner
    if owner is None:
        log.warning("auto generate skipped for %s: batch has no owner", cluster.id)
        return
    try:
        ensure_cluster_generations(db, cluster, owner)
        cluster.auto_generate = False
        db.commit()
    except ValueError as exc:
        db.rollback()
        log.warning("auto generate skipped for %s: %s", cluster.id, exc)
