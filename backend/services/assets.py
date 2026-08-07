"""上传素材登记：校验、归一化、自动建 Cluster。"""
from __future__ import annotations

import hashlib
import io
import uuid

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from ..models import Asset, Batch, Cluster, ClusterAsset
from ..storage import StorageError, get_storage

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TXT_BYTES = 256 * 1024
MAX_PROJECT_IMAGES = 100
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
_IMAGE_SUFFIX_MAP = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".png"}


class UploadError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def active_project_image_count(db: Session, batch: Batch) -> int:
    return (
        db.query(Asset)
        .filter_by(batch_id=batch.id, kind="image")
        .filter(Asset.archived_at.is_(None))
        .count()
    )


def remaining_project_image_capacity(db: Session, batch: Batch) -> int:
    return max(0, MAX_PROJECT_IMAGES - active_project_image_count(db, batch))


def ensure_project_image_capacity(db: Session, batch: Batch, incoming: int = 1) -> None:
    if incoming <= 0:
        return
    remaining = remaining_project_image_capacity(db, batch)
    if incoming > remaining:
        raise UploadError(
            "project_image_limit",
            f"每个项目最多 {MAX_PROJECT_IMAGES} 张图片，当前还可导入 {remaining} 张",
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_image(data: bytes, filename: str) -> tuple[bytes, str, int, int]:
    """返回 (normalized_bytes, content_type, width, height)。"""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise UploadError("unsupported_format", "仅支持 JPEG、PNG、WebP 图片和 UTF-8 TXT")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        fmt = image.format
        if fmt not in ALLOWED_IMAGE_FORMATS:
            raise UploadError("unsupported_format", "仅支持 JPEG、PNG、WebP 图片和 UTF-8 TXT")
        if getattr(image, "is_animated", False):
            raise UploadError("unsupported_format", "暂不支持动态 WebP")
    except UploadError:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise UploadError("invalid_image", "图片文件损坏或内容与扩展名不一致") from None
    width, height = image.size
    if fmt == "WEBP":
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        normalized = buffer.getvalue()
        content_type = "image/png"
    else:
        normalized = data
        content_type = "image/jpeg" if fmt == "JPEG" else "image/png"
    return normalized, content_type, width, height


def register_uploaded_asset(
    db: Session,
    batch: Batch,
    filename: str,
    data: bytes,
    content_type: str,
    mode: str,
    actor_id=None,
) -> Asset:
    storage = get_storage()
    if filename.lower().endswith(".txt"):
        if len(data) > MAX_TXT_BYTES:
            raise UploadError("file_too_large", "TXT 不能超过 256 KiB")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadError("invalid_encoding", "TXT 必须使用 UTF-8 编码") from None
        storage_path = f"originals/{batch.id}/{uuid.uuid4().hex}.txt"
        try:
            storage.save(storage_path, data)
        except OSError:
            raise UploadError("storage_unavailable", "素材存储暂时不可用，请稍后重试该文件") from None
        asset = Asset(
            batch_id=batch.id,
            kind="txt",
            original_filename=filename,
            storage_path=storage_path,
            sha256=_sha256(data),
            file_size=len(data),
            content_type="text/plain",
            text_content=text,
        )
        db.add(asset)
        db.flush()
        _refresh_batch_seed_prompt(db, batch)
        return asset

    if len(data) > MAX_IMAGE_BYTES:
        raise UploadError("file_too_large", "图片不能超过 20 MiB")
    ensure_project_image_capacity(db, batch, 1)
    normalized, forced_content_type, width, height = _validate_image(data, filename)
    storage_path = f"originals/{batch.id}/{uuid.uuid4().hex}"
    suffix = _IMAGE_SUFFIX_MAP.get(_image_format(normalized), ".png")
    storage_path += suffix
    try:
        storage.save(storage_path, normalized)
    except OSError:
        raise UploadError("storage_unavailable", "素材存储暂时不可用，请稍后重试该文件") from None
    asset = Asset(
        batch_id=batch.id,
        kind="image",
        original_filename=filename,
        storage_path=storage_path,
        sha256=_sha256(normalized),
        file_size=len(normalized),
        content_type=forced_content_type or content_type,
        width=width,
        height=height,
    )
    db.add(asset)
    db.flush()
    cluster = Cluster(
        batch_id=batch.id,
        name=filename,
        preparation_status="draft",
        preparation_stage="draft",
        preparation_total=7,
    )
    db.add(cluster)
    db.flush()
    db.add(ClusterAsset(cluster_id=cluster.id, asset_id=asset.id, role="primary", order=1))
    db.flush()
    if mode == "auto":
        request_cluster_preparation(cluster, auto_generate=True)
    if batch.status in {"draft", "uploading"} or batch.last_import_mode != mode:
        batch.status = "organizing"
        batch.last_import_mode = mode
    return asset


def _image_format(data: bytes) -> str:
    try:
        return Image.open(io.BytesIO(data)).format or "PNG"
    except Exception:
        return "PNG"


def _refresh_batch_seed_prompt(db: Session, batch: Batch) -> None:
    texts = [
        a.text_content
        for a in db.query(Asset).filter_by(batch_id=batch.id, kind="txt").order_by(Asset.created_at, Asset.id).all()
    ]
    batch.global_prompt = "\n".join(t for t in texts if t)


def request_cluster_preparation(cluster: Cluster, auto_generate: bool = False) -> Cluster:
    cluster.auto_generate = auto_generate
    cluster.preparation_status = "pending"
    cluster.preparation_error = ""
    cluster.preparation_stage = "queued"
    cluster.preparation_current = 0
    cluster.preparation_total = 7
    return cluster
