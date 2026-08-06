"""Generation worker queue claiming regression check.

Queued jobs must not count as active work; otherwise a backlog can make the worker
think capacity is full forever and leave every job at 0%.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.db import SessionLocal, init_db
from backend.models import Batch, Cluster, Generation, User
from backend.seed import seed_output_template
from backend.services.template import global_fallback_template, template_slots
from backend.workers.generation_worker import _active_count, _claim_queued, _recover_orphaned_submitting


def main() -> None:
    init_db()
    db = SessionLocal()
    marker = uuid.uuid4().hex[:8]
    claimed_to_restore: list[str] = []
    batch_id = None
    try:
        seed_output_template(db)
        old_batches = db.query(Batch).filter(Batch.name.like("__claim_test_%")).all()
        for old_batch in old_batches:
            db.query(Generation).filter_by(batch_id=old_batch.id).delete(synchronize_session=False)
            db.query(Cluster).filter_by(batch_id=old_batch.id).delete(synchronize_session=False)
            db.delete(old_batch)
        db.flush()

        user = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        assert user is not None, "missing admin user"
        template = global_fallback_template(db)
        slot = template_slots(template)[0]

        batch = Batch(owner_id=user.id, name=f"__claim_test_{marker}", output_template_id=template.id)
        db.add(batch)
        db.flush()
        batch_id = batch.id
        cluster = Cluster(batch_id=batch.id, name=f"__claim_cluster_{marker}", sku=f"CLAIM-{marker}")
        db.add(cluster)
        db.flush()

        before = _active_count(db)
        for attempt in range(1, 4):
            db.add(
                Generation(
                    batch_id=batch.id,
                    cluster_id=cluster.id,
                    output_slot_id=slot.id,
                    created_by_id=user.id,
                    attempt=attempt,
                    status="queued",
                    prompt_text="queued prompt",
                )
            )
        db.flush()
        assert _active_count(db) == before, "queued backlog must not consume worker capacity"

        db.add(
            Generation(
                batch_id=batch.id,
                cluster_id=cluster.id,
                output_slot_id=slot.id,
                created_by_id=user.id,
                attempt=4,
                status="submitted",
                prompt_text="submitted prompt",
            )
        )
        db.flush()
        assert _active_count(db) == before + 1, "submitted job should consume worker capacity"

        db.add(
            Generation(
                batch_id=batch.id,
                cluster_id=cluster.id,
                output_slot_id=slot.id,
                created_by_id=user.id,
                attempt=5,
                status="submitting",
                prompt_text="orphan submitting prompt",
            )
        )
        db.flush()

        recovered = _recover_orphaned_submitting(db)
        assert recovered >= 1
        assert db.query(Generation).filter_by(batch_id=batch.id, status="submitting").count() == 0
        assert db.query(Generation).filter_by(batch_id=batch.id, status="queued").count() == 4

        future_generations: list[Generation] = []
        for offset in range(9):
            generation = Generation(
                batch_id=batch.id,
                cluster_id=cluster.id,
                output_slot_id=slot.id,
                created_by_id=user.id,
                attempt=10 + offset,
                status="queued",
                prompt_text="future prompt",
                created_at=datetime(2099, 1, 1, 0, offset, tzinfo=timezone.utc),
            )
            db.add(generation)
            future_generations.append(generation)
        db.flush()

        claimed_to_restore = _claim_queued(db, 100)
        newest_eight = {
            str(g.id)
            for g in sorted(future_generations, key=lambda item: item.created_at, reverse=True)[:8]
        }
        assert set(claimed_to_restore) == newest_eight, "worker should claim a small newest-first batch"

        db.rollback()
        print("PASS: generation worker queued jobs do not block claiming")
    finally:
        if claimed_to_restore:
            db.query(Generation).filter(Generation.id.in_([uuid.UUID(item) for item in claimed_to_restore])).update(
                {"status": "queued"}, synchronize_session=False
            )
        if batch_id is not None:
            db.query(Generation).filter_by(batch_id=batch_id).delete(synchronize_session=False)
            db.query(Cluster).filter_by(batch_id=batch_id).delete(synchronize_session=False)
            db.query(Batch).filter_by(id=batch_id).delete(synchronize_session=False)
        db.commit()
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
