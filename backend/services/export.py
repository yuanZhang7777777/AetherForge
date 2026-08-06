"""导出 ZIP：图片 + 导出清单.csv（UTF-8 BOM）。"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date

from sqlalchemy.orm import Session

from ..models import Batch, Cluster, Generation
from ..storage import StorageError, get_storage

MAX_EXPORT_RESULT_BYTES = 25 * 1024 * 1024
MAX_EXPORT_TOTAL_BYTES = 500 * 1024 * 1024
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

_CONTROL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_part(value: str, fallback: str) -> str:
    cleaned = _CONTROL.sub("", value).strip().replace(" ", "_")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or fallback


def _selected_generations(db: Session, batch: Batch, requested_ids: list[str]) -> list[Generation]:
    query = (
        db.query(Generation)
        .filter_by(batch_id=batch.id, status="completed")
        .join(Cluster, Cluster.id == Generation.cluster_id)
        .filter(Cluster.archived_at.is_(None))
    )
    if requested_ids:
        from ..ids import safe_uuid

        ids = [safe_uuid(i) for i in requested_ids]
        ids = [i for i in ids if i is not None]
        if not ids:
            return []
        return (
            query.filter(Generation.id.in_(ids))
            .order_by(Cluster.name, Generation.output_slot_id, Generation.attempt.desc())
            .all()
        )
    latest: dict = {}
    for generation in query.order_by(
        Generation.cluster_id, Generation.output_slot_id, Generation.attempt.desc(), Generation.id.desc()
    ).all():
        latest.setdefault((generation.cluster_id, generation.output_slot_id), generation)
    return list(latest.values())


def build_export_zip(db: Session, batch: Batch, requested_ids: list[str]):
    storage = get_storage()
    generations = _selected_generations(db, batch, requested_ids)
    if not generations:
        raise ValueError("No completed images are available to export")

    root_name = _safe_part(f"{batch.name}_{date.today():%Y%m%d}", "project")
    buffer = io.BytesIO()
    entries: list[dict] = []
    total_bytes = 0
    used_names: set[str] = set()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for generation in generations:
            cluster = generation.cluster
            slot = generation.output_slot
            result = next(iter(generation.result_assets), None)
            if result is None:
                continue
            try:
                data = storage.read(result.storage_path)
            except (FileNotFoundError, StorageError, OSError):
                continue
            if len(data) > MAX_EXPORT_RESULT_BYTES:
                raise ValueError("A completed result is too large to export")
            total_bytes += len(data)
            if total_bytes > MAX_EXPORT_TOTAL_BYTES:
                raise ValueError("The requested export is too large")

            suffix = _safe_suffix(result.storage_path)
            product = _safe_part(cluster.product_name or cluster.name, "product")
            sku = _safe_part(cluster.sku or "", "")
            folder = f"{product}__{sku}" if sku else product
            slot_name = _safe_part(slot.name, f"slot-{slot.order}")
            base_name = f"{slot.order:02d}_{slot_name}{suffix}"
            filename = _unique_name(used_names, base_name)
            archive.writestr(f"{root_name}/{folder}/{filename}", data)
            entries.append(
                {
                    "generation_id": str(generation.id),
                    "product": cluster.product_name or cluster.name,
                    "sku": cluster.sku or "",
                    "slot_order": slot.order,
                    "slot_name": slot.name,
                    "attempt": generation.attempt,
                    "filename": f"{folder}/{filename}",
                }
            )

        if not entries:
            raise ValueError("No completed images are available to export")

        manifest = io.StringIO()
        manifest.write("﻿")
        writer = csv.writer(manifest)
        writer.writerow(
            ["generation_id", "product", "sku", "slot_order", "slot_name", "attempt", "filename"]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry["generation_id"],
                    entry["product"],
                    entry["sku"],
                    entry["slot_order"],
                    entry["slot_name"],
                    entry["attempt"],
                    entry["filename"],
                ]
            )
        archive.writestr(f"{root_name}/导出清单.csv", manifest.getvalue().encode("utf-8"))

    return buffer.getvalue(), f"{root_name}.zip"


def _safe_suffix(storage_path: str) -> str:
    suffix = _CONTROL.sub("", storage_path.rsplit(".", 1)[-1].lower()) if "." in storage_path else ""
    suffix = f".{suffix}"
    return suffix if suffix in _ALLOWED_SUFFIXES else ".bin"


def _unique_name(used: set[str], base: str) -> str:
    if base not in used:
        used.add(base)
        return base
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    index = 2
    while True:
        candidate = f"{stem}_{index}{dot}{suffix}" if dot else f"{stem}_{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1
