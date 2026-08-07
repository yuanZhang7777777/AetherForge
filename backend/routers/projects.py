"""项目路由：create/settings/snapshot/progress/prepare/assets/sku-import/confirm/generate/pause/preflight/export。"""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import require_user, session_from
from ..db import get_db
from ..models import Batch, Cluster, User
from ..schemas import (
    ExportRequest,
    GenerateRequest,
    PauseRequest,
    PrepareRequest,
    ProductConfiguration,
    ProjectInput,
    SkuImportRequest,
)
from ..services.assets import (
    MAX_PROJECT_IMAGES,
    UploadError,
    register_uploaded_asset,
    remaining_project_image_capacity,
    request_cluster_preparation,
)
from ..services.catalog import import_skus as import_catalog_skus
from ..services.batches import (
    create_project,
    export_selected_generations,
    request_preparation_items,
    update_project_settings,
)
from ..services.contract import cluster_preparation_is_current
from ..services.generation import ensure_cluster_generations, pause_project_work
from ..services.preflight import preflight_batch
from ..services.serialize import (
    _public_product_name,
    serialize_project,
    serialize_project_progress,
)
from ..services.template import global_fallback_template
from ._helpers import coerce_uuid

router = APIRouter(prefix="/api/projects", tags=["projects"])

_DISPOSITION_UNSAFE = re.compile(r'[^A-Za-z0-9._-]+')


def _attachment_disposition(filename: str) -> str:
    ascii_name = _DISPOSITION_UNSAFE.sub("_", filename).strip("._") or "export.zip"
    if not ascii_name.lower().endswith(".zip"):
        ascii_name += ".zip"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def _get_batch(db: Session, project_id: str, user: User | None = None) -> Batch:
    batch = db.get(Batch, coerce_uuid(project_id, "项目不存在"))
    if batch is None:
        raise HTTPException(404, "项目不存在")
    if user is not None and batch.owner_id != user.id:
        raise HTTPException(404, "项目不存在")
    return batch


@router.post("/", status_code=201)
def create(payload: ProjectInput, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = create_project(db, user, payload.name)
    db.commit()
    return serialize_project(db, batch)


@router.get("/{project_id}/snapshot/")
def snapshot(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    return serialize_project(db, batch)


@router.get("/{project_id}/progress/")
def progress(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    return serialize_project_progress(db, batch)


@router.patch("/{project_id}/settings/")
def settings(project_id: str, payload: ProductConfiguration, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    update_project_settings(
        db,
        batch,
        platform=payload.platform,
        market=payload.market,
        size=payload.size,
        resolution=payload.resolution,
        global_prompt=payload.global_prompt,
        ai_recognition_enabled=payload.ai_recognition_enabled,
    )
    db.commit()
    return serialize_project(db, batch)


@router.post("/{project_id}/prepare/")
def prepare(project_id: str, payload: PrepareRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    items = request_preparation_items(db, batch, payload.cluster_ids)
    db.commit()
    return {"items": items}



@router.post("/{project_id}/assets/")
async def upload_assets(
    project_id: str,
    request: Request,
    files: list[UploadFile] = File(default=[]),
    relative_paths: list[str] = Form(default=[]),
    mode: str = Form("organize"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    paths = list(relative_paths) or [f.filename or "file" for f in files]
    result: dict = {"asset_count": 0, "imported": [], "rejected": []}
    if not files:
        return result
    image_count = sum(1 for p in paths if not p.lower().endswith(".txt"))
    txt_count = len(paths) - image_count
    if image_count > 100 or txt_count > 20:
        raise HTTPException(400, "单次最多上传 100 张图片和 20 个 TXT")

    image_slots = remaining_project_image_capacity(db, batch)
    for file, rel in zip(files, paths):
        is_image = not rel.lower().endswith(".txt")
        if is_image and image_slots <= 0:
            result["rejected"].append(
                {"filename": rel, "code": "project_image_limit", "message": f"每个项目最多 {MAX_PROJECT_IMAGES} 张图片"}
            )
            continue
        try:
            data = await file.read()
        except Exception:
            result["rejected"].append({"filename": rel, "code": "read_failed", "message": "读取文件失败"})
            continue
        try:
            asset = register_uploaded_asset(db, batch, rel, data, file.content_type or "", mode, user.id)
        except UploadError as exc:
            result["rejected"].append({"filename": rel, "code": exc.code, "message": exc.message})
            continue
        except Exception as exc:
            db.rollback()
            result["rejected"].append({"filename": rel, "code": "upload_failed", "message": str(exc)})
            continue
        if is_image:
            image_slots -= 1
        result["asset_count"] += 1
        cluster_id = str(asset.cluster_asset.cluster_id) if asset.cluster_asset else None
        result["imported"].append({"filename": rel, "asset_id": str(asset.id), "cluster_id": cluster_id})
    db.commit()
    return result


@router.post("/{project_id}/sku-import/")
def sku_import(project_id: str, payload: SkuImportRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    session = session_from(request) or {}
    return import_catalog_skus(
        db,
        batch,
        payload.skus,
        erp_token=str(session.get("erp_token") or ""),
        mode=payload.mode,
    )


@router.post("/{project_id}/confirm/")
def confirm(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    clusters = (
        db.query(Cluster)
        .filter_by(batch_id=batch.id)
        .filter(Cluster.archived_at.is_(None))
        .all()
    )
    return _run_generation(db, batch, user, [str(c.id) for c in clusters], [])


@router.post("/{project_id}/generate/")
def generate(project_id: str, payload: GenerateRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    return _run_generation(db, batch, user, payload.cluster_ids, payload.slot_orders)


def _run_generation(db: Session, batch: Batch, user: User, cluster_ids: list[str], slot_orders: list[int]):
    items: list[dict] = []
    count = 0
    for cluster_id in dict.fromkeys(cluster_ids):
        try:
            cluster_pk = coerce_uuid(cluster_id, "商品不存在")
        except HTTPException:
            items.append({"cluster_id": cluster_id, "status": "error", "code": "cluster_not_found", "message": "商品不存在"})
            continue
        cluster = db.get(Cluster, cluster_pk)
        if cluster is None or cluster.batch_id != batch.id or cluster.archived_at is not None:
            items.append({"cluster_id": cluster_id, "status": "error", "code": "cluster_not_found", "message": "商品不存在"})
            continue
        if not _public_product_name(cluster):
            items.append({"cluster_id": cluster_id, "status": "error", "code": "name_required", "message": "请先填写商品名称"})
            continue
        if not cluster_preparation_is_current(cluster):
            items.append(
                {
                    "cluster_id": cluster_id,
                    "status": "error",
                    "code": "preparation_stale",
                    "message": "尚未预备生成，或平台/国家/商品信息已变更，请先重新预备生成",
                }
            )
            continue
        try:
            created = ensure_cluster_generations(db, cluster, user, slot_orders or None)
        except ValueError as exc:
            items.append({"cluster_id": cluster_id, "status": "error", "code": "prompt_not_ready", "message": str(exc)})
            continue
        count += len(created)
        items.append({"cluster_id": cluster_id, "status": "queued" if created else "noop"})
    db.commit()
    return {"generation_count": count, "items": items}


@router.post("/{project_id}/pause/")
def pause(project_id: str, payload: PauseRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    result = pause_project_work(db, batch, payload.cluster_ids, payload.generation_ids)
    db.commit()
    return result


@router.post("/{project_id}/preflight/")
def preflight(project_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    template = batch.output_template or global_fallback_template(db)
    full = preflight_batch(db, batch, user, template)
    return {
        "cluster_count": full["cluster_count"],
        "slot_count": full["slot_count"],
        "generation_count": full["generation_count"],
        "blocking_errors": full["blocking_errors"],
    }


@router.post("/{project_id}/export/")
def export(project_id: str, payload: ExportRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    batch = _get_batch(db, project_id, user)
    try:
        data, filename = export_selected_generations(db, batch, payload.generation_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": _attachment_disposition(filename)},
    )
