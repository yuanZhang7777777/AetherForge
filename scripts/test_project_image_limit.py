"""Project image cap regression: one project can hold at most 100 active images."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT if (ROOT / "backend").is_dir() else Path("/app")))

from backend.db import SessionLocal, init_db
from backend.models import Asset, Batch, Cluster, ClusterAsset, SkuImportItem, User
from backend.services import catalog as catalog_module
from backend.services.assets import ensure_project_image_capacity, remaining_project_image_capacity


def main() -> None:
    init_db()
    db = SessionLocal()
    marker = uuid.uuid4().hex[:8]
    batch_id = None
    original_settings = catalog_module.settings
    original_client = catalog_module.CatalogClient
    original_download = catalog_module.download_catalog_image
    try:
        user = db.query(User).filter_by(role="admin").order_by(User.created_at).first()
        assert user is not None, "missing admin user"

        batch = Batch(owner_id=user.id, name=f"__image_limit_test_{marker}")
        db.add(batch)
        db.flush()
        batch_id = batch.id
        for index in range(100):
            db.add(_asset(batch, f"{index}.png"))
        db.flush()

        assert remaining_project_image_capacity(db, batch) == 0
        try:
            ensure_project_image_capacity(db, batch, 1)
        except Exception as exc:
            assert getattr(exc, "code", "") == "project_image_limit"
        else:
            raise AssertionError("expected project_image_limit")

        first = db.query(Asset).filter_by(batch_id=batch.id, kind="image").first()
        assert first is not None
        first.archived_at = datetime.now(timezone.utc)
        db.flush()
        assert remaining_project_image_capacity(db, batch) == 1
        ensure_project_image_capacity(db, batch, 1)

        first.archived_at = None
        db.flush()

        class FakeCatalogClient:
            def __init__(self, *args, **kwargs):
                pass

            def fetch_products(self, skus):
                return {sku: {"sku": sku, "productName": "Limit Product", "pic": "http://example.invalid/a.jpg"} for sku in skus}

        def forbidden_download(*args, **kwargs):
            raise AssertionError("image limit should block before ERP image download")

        catalog_module.settings = SimpleNamespace(catalog_query_url="http://catalog.test", catalog_max_skus_per_request=50)
        catalog_module.CatalogClient = FakeCatalogClient
        catalog_module.download_catalog_image = forbidden_download

        result = catalog_module.import_skus(db, batch, ["SKU-LIMIT"], erp_token="token")
        assert result["imported"] == 0
        assert result["failed"] == 1
        assert result["items"][0]["errorCode"] == "project_image_limit"
        print("PASS: project image cap blocks upload and SKU image imports")
    finally:
        catalog_module.settings = original_settings
        catalog_module.CatalogClient = original_client
        catalog_module.download_catalog_image = original_download
        db.rollback()
        if batch_id is not None:
            _cleanup_batch(db, batch_id)
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


def _cleanup_batch(db, batch_id) -> None:
    cluster_ids = [row[0] for row in db.query(Cluster.id).filter_by(batch_id=batch_id).all()]
    if cluster_ids:
        db.query(ClusterAsset).filter(ClusterAsset.cluster_id.in_(cluster_ids)).delete(synchronize_session=False)
    db.query(SkuImportItem).filter_by(batch_id=batch_id).delete(synchronize_session=False)
    db.query(Asset).filter_by(batch_id=batch_id).delete(synchronize_session=False)
    db.query(Cluster).filter_by(batch_id=batch_id).delete(synchronize_session=False)
    db.query(Batch).filter_by(id=batch_id).delete(synchronize_session=False)
    db.commit()


if __name__ == "__main__":
    main()
