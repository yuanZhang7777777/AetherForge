"""Cluster 路由：乐观锁更新、merge、delete。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Cluster
from ..schemas import ClusterUpdateRequest, MergeRequest
from ..services.clusters import (
    ClusterArchived,
    ClusterConflict,
    ClusterNotFound,
    delete_cluster,
    merge_asset_into_cluster,
    update_cluster,
)
from ._helpers import coerce_uuid

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


def _get_cluster(db: Session, cluster_id: str) -> Cluster:
    cluster = db.get(Cluster, coerce_uuid(cluster_id, "商品不存在"))
    if cluster is None:
        raise HTTPException(404, "商品不存在")
    return cluster


@router.post("/{cluster_id}/")
def update(
    cluster_id: str,
    payload: ClusterUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cluster = _get_cluster(db, cluster_id)
    try:
        update_cluster(db, cluster, payload.expected_version, payload.model_dump(exclude={"expected_version"}), user.id)
    except ClusterConflict:
        db.rollback()
        raise HTTPException(409, "商品信息刚刚更新，请刷新后再保存") from None
    except ClusterArchived as exc:
        db.rollback()
        raise HTTPException(410, str(exc)) from None
    db.commit()
    return {"id": str(cluster.id), "version": cluster.version}


@router.post("/{cluster_id}/merge/")
def merge(
    cluster_id: str,
    payload: MergeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    cluster = _get_cluster(db, cluster_id)
    try:
        merge_asset_into_cluster(db, cluster, payload.asset_id, payload.expected_version, user.id)
    except ClusterConflict:
        db.rollback()
        raise HTTPException(409, "商品信息刚刚更新，请刷新后再保存") from None
    except ClusterNotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    db.commit()
    return {"id": str(cluster.id), "version": cluster.version}


@router.delete("/{cluster_id}/")
def delete(cluster_id: str, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    cluster = _get_cluster(db, cluster_id)
    delete_cluster(db, cluster)
    db.commit()
    return {"status": "archived"}
