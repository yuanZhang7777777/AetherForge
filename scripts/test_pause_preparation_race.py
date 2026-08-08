"""Pause race regression: a running prepare job must not requeue after pause."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.db import SessionLocal, init_db
from backend.models import Batch, Cluster, User
from backend.services.contract import invalidate_preparation
from backend.workers import prepare_run


def main() -> None:
    init_db()
    db = SessionLocal()
    marker = uuid.uuid4().hex[:8]
    original = prepare_run.run_cluster_preparation
    try:
        user = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        assert user is not None, "missing admin user"
        batch = Batch(owner_id=user.id, name=f"__pause_test_{marker}")
        db.add(batch)
        db.flush()
        cluster = Cluster(
            batch_id=batch.id,
            name="paused item",
            preparation_status="preparing",
            preparation_stage="N2",
            analysis_snapshot={"_preparation_revision": 1},
        )
        db.add(cluster)
        db.commit()

        def fake_prepare(job_db, job_cluster, actor_id=None, claimed_revision=None):
            invalidate_preparation(job_cluster)
            return True

        prepare_run.run_cluster_preparation = fake_prepare
        prepare_run.run_prepare_job(cluster.id, 1)
        db.refresh(cluster)

        assert cluster.preparation_status == "draft", cluster.preparation_status
        assert cluster.preparation_stage == "draft", cluster.preparation_stage
        print("PASS: paused prepare job stays paused")
    finally:
        prepare_run.run_cluster_preparation = original
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
