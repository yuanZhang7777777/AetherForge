"""prompt-worker：独立进程，循环认领 pending 的 cluster 并执行 prepare 管线。"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import Cluster

log = logging.getLogger("aetherforge.prompt_worker")

CLAIM_BATCH = 400
CLAIM_BACKOFF_SECONDS = 2.0


def _claim_pending(db) -> list[tuple[str, int]]:
    rows = db.execute(
        select(Cluster.id, Cluster.updated_at)
        .where(Cluster.preparation_status == "pending", Cluster.archived_at.is_(None))
        .order_by(Cluster.updated_at, Cluster.created_at)
        .limit(CLAIM_BATCH)
    ).all()
    claimed: list[tuple[str, int]] = []
    for cluster_id, _updated_at in rows:
        cluster = db.get(Cluster, cluster_id)
        if cluster is None or cluster.preparation_status != "pending":
            continue
        revision = int((cluster.analysis_snapshot or {}).get("_preparation_revision", 0))
        cluster.preparation_status = "preparing"
        cluster.preparation_stage = "queued"
        cluster.preparation_error = ""
        claimed.append((str(cluster.id), revision))
    if claimed:
        db.commit()
    return claimed


def _process(cluster_id: str, claimed_revision: int) -> None:
    from .prepare_run import run_prepare_job

    run_prepare_job(cluster_id, claimed_revision)


def _main_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                claimed = _claim_pending(db)
            if claimed:
                workers = min(settings.max_concurrent_prepares, len(claimed))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(lambda item: _process(*item), claimed))
                continue
        except Exception:
            log.exception("prompt worker iteration failed")
        time.sleep(CLAIM_BACKOFF_SECONDS)


def run() -> None:
    from ..db import wait_for_tables

    wait_for_tables()
    log.info("prompt-worker started")
    _main_loop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
