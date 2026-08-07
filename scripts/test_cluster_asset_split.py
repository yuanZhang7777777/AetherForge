"""Cluster asset split regression: dragging an image out must reparent the link."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.db import SessionLocal, init_db
from backend.models import Asset, Batch, Cluster, ClusterAsset, User
from backend.seed import seed_output_template
from backend.services.clusters import split_asset_out


def main() -> None:
    init_db()
    db = SessionLocal()
    marker = uuid.uuid4().hex[:8]
    try:
        seed_output_template(db)
        user = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        assert user is not None, "missing admin user"

        batch = Batch(owner_id=user.id, name=f"__split_test_{marker}")
        db.add(batch)
        db.flush()
        source = Cluster(batch_id=batch.id, name="source", preparation_status="ready", preparation_stage="ready")
        db.add(source)
        db.flush()
        first = _asset(batch, "first.png")
        second = _asset(batch, "second.png")
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                ClusterAsset(cluster_id=source.id, asset_id=first.id, role="primary", order=1),
                ClusterAsset(cluster_id=source.id, asset_id=second.id, role="reference", order=2),
            ]
        )
        db.flush()

        new_cluster = split_asset_out(db, first)
        db.flush()

        moved = db.query(ClusterAsset).filter_by(asset_id=first.id).one()
        remaining = db.query(ClusterAsset).filter_by(cluster_id=source.id).one()
        assert moved.cluster_id == new_cluster.id
        assert moved.role == "primary"
        assert moved.order == 1
        assert remaining.asset_id == second.id
        assert remaining.role == "primary"
        assert remaining.order == 1
        assert source.archived_at is None
        assert source.preparation_status == "pending"
        assert db.query(ClusterAsset).filter_by(asset_id=first.id).count() == 1
        print("PASS: split asset reuses existing ClusterAsset link")
    finally:
        db.rollback()
        db.close()


def _asset(batch: Batch, name: str) -> Asset:
    return Asset(
        batch_id=batch.id,
        kind="image",
        original_filename=name,
        storage_path=f"originals/{batch.id}/{uuid.uuid4().hex}.png",
        sha256=uuid.uuid4().hex.ljust(64, "0"),
        file_size=1,
        content_type="image/png",
        width=100,
        height=100,
    )


if __name__ == "__main__":
    main()
