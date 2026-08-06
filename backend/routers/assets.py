"""素材路由：delete/split/media（asset 与 result 图片）。"""
from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Asset, ResultAsset
from ..services.clusters import ClusterNotFound, delete_asset, split_asset_out
from ..storage import get_storage
from ._helpers import coerce_uuid

router = APIRouter(prefix="/api", tags=["assets"])

_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _media_response(storage_path: str) -> Response:
    try:
        data = get_storage().read(storage_path)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "文件不存在") from None
    suffix = PurePosixPath(storage_path).suffix.lower()
    return Response(content=data, media_type=_IMAGE_TYPES.get(suffix, "application/octet-stream"))


@router.delete("/assets/{asset_id}/")
def delete(asset_id: str, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    asset = db.get(Asset, coerce_uuid(asset_id, "素材不存在"))
    if asset is None:
        raise HTTPException(404, "素材不存在")
    delete_asset(db, asset)
    db.commit()
    return {"status": "archived"}


@router.post("/assets/{asset_id}/split/")
def split(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    asset = db.get(Asset, coerce_uuid(asset_id, "素材不存在"))
    if asset is None:
        raise HTTPException(404, "素材不存在")
    try:
        cluster = split_asset_out(db, asset, user.id)
    except ClusterNotFound as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return {"id": str(cluster.id), "version": cluster.version}


@router.get("/assets/{asset_id}/media/")
def asset_media(asset_id: str, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    asset = db.get(Asset, coerce_uuid(asset_id, "素材不存在"))
    if asset is None or asset.kind != "image":
        raise HTTPException(404, "素材不存在")
    return _media_response(asset.storage_path)


@router.get("/results/{result_id}/media/")
def result_media(result_id: str, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    result = db.get(ResultAsset, coerce_uuid(result_id, "结果不存在"))
    if result is None:
        raise HTTPException(404, "结果不存在")
    return _media_response(result.storage_path)
