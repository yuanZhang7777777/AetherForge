"""ERP 商品目录导入：拉取 SKU 的名称与图片，建档/回填，不覆盖已有商品卡信息。

对齐旧 picturesGenerate import_skus：CatalogClient.fetch_products 查 queryGoodsSales，
图片下载带 host 白名单 + 重定向/体积限制；已存在的 cluster 只回填空名称，绝不覆盖用户填写。
"""
from __future__ import annotations

import hashlib
import ipaddress
import uuid

import requests
from sqlalchemy.orm import Session
from urllib.parse import urljoin, urlparse

from ..config import settings
from ..models import Asset, Batch, Cluster, ClusterAsset, SkuImportItem
from ..storage import get_storage
from .assets import UploadError, _sha256, _validate_image, request_cluster_preparation

_FALLBACK_NAME = "名称待确认"


class CatalogError(Exception):
    pass


class CatalogAuthError(Exception):
    pass


def _catalog_response_data(response, expected_type):
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise CatalogError("Catalog service is unavailable") from exc
    status = payload.get("status") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("success") is not True
        or ("code" in payload and payload["code"] not in (200, "200"))
        or (status is not None and status not in (True, 200, "200", "ok", "success"))
        or not isinstance(payload.get("data"), expected_type)
    ):
        raise CatalogError("Catalog service returned an invalid response")
    return payload["data"]


class CatalogClient:
    def __init__(self, token=None, session=None, timeout=None):
        self.session = session or requests.Session()
        self.timeout = timeout or settings.catalog_timeout_seconds
        self._token = str(token or "").strip()

    def fetch_products(self, skus: list[str]) -> dict:
        if not self._token:
            raise CatalogAuthError("ERP login expired")
        if not settings.catalog_query_url:
            raise CatalogError("Catalog service is not configured")
        try:
            response = self.session.post(
                settings.catalog_query_url,
                json={"skuList": list(skus)},
                headers={"Authorization": self._token},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CatalogError("Catalog service is unavailable") from exc
        if response.status_code in {401, 403}:
            raise CatalogAuthError("ERP login expired")
        data = _catalog_response_data(response, list)
        requested = set(skus)
        products: dict = {}
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("sku"), str):
                raise CatalogError("Catalog service returned an invalid response")
            sku = item["sku"].strip()
            if not sku or sku not in requested:
                continue
            products[sku] = {
                "sku": sku,
                "productName": str(item.get("productName") or ""),
                "pic": str(item.get("pic") or ""),
            }
        return products


def _catalog_image_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    host = (parsed.hostname or "").lower()
    allowed = {str(address).strip().lower() for address in settings.catalog_allowed_image_hosts}
    if parsed.scheme not in {"http", "https"} or not host or host not in allowed or parsed.username or parsed.password:
        raise CatalogError("Catalog image is not allowed")
    try:
        address = ipaddress.ip_address(host)
        if (
            not address.is_global
            or address.is_multicast
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        ):
            raise CatalogError("Catalog image is not allowed")
    except ValueError as exc:
        raise CatalogError("Catalog image is not allowed") from exc
    return parsed.geturl()


def download_catalog_image(url: str, session=None) -> tuple[bytes, str]:
    current = _catalog_image_url(url)
    session = session or requests.Session()
    max_redirects = 3
    for _ in range(max_redirects + 1):
        try:
            response = session.get(current, timeout=settings.catalog_timeout_seconds, stream=True, allow_redirects=False)
        except requests.RequestException as exc:
            raise CatalogError("Catalog image could not be downloaded") from exc
        try:
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise CatalogError("Catalog image could not be downloaded")
                current = _catalog_image_url(urljoin(current, location))
                continue
            if response.status_code != 200:
                raise CatalogError("Catalog image could not be downloaded")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if content_type not in {"image/jpeg", "image/png"}:
                raise CatalogError("Catalog image is not supported")
            try:
                content_length = int(response.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise CatalogError("Catalog image could not be downloaded") from exc
            if content_length > settings.catalog_max_image_bytes:
                raise CatalogError("Catalog image is too large")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(64 * 1024):
                total += len(chunk)
                if total > settings.catalog_max_image_bytes:
                    raise CatalogError("Catalog image is too large")
                chunks.append(chunk)
            return b"".join(chunks), content_type
        finally:
            response.close()
    raise CatalogError("Catalog image redirects too many times")


def _backfill_name(current: str, product_name: str) -> str:
    name = (current or "").strip()
    if name in {"", _FALLBACK_NAME} and product_name:
        return product_name
    return current


def _register_image_asset(db: Session, batch: Batch, sku: str, data: bytes, content_type: str, width: int, height: int) -> Asset:
    suffix = ".jpg" if content_type == "image/jpeg" else ".png"
    storage_path = f"originals/{batch.id}/{uuid.uuid4().hex}{suffix}"
    get_storage().save(storage_path, data)
    asset = Asset(
        batch_id=batch.id,
        kind="image",
        original_filename=f"{sku}{suffix}",
        storage_path=storage_path,
        sha256=_sha256(data),
        file_size=len(data),
        content_type=content_type,
        width=width,
        height=height,
    )
    db.add(asset)
    db.flush()
    return asset


def _fail_item(sku: str, code: str, message: str) -> dict:
    return {"sku": sku, "productName": "", "status": "failed", "clusterId": None, "errorCode": code, "message": message}


def _record_import(
    db: Session,
    batch: Batch,
    cluster: Cluster,
    sku: str,
    product_name: str,
    status: str = "imported",
    error_message: str = "",
) -> None:
    """记录一次导入；同 SKU 反复导入复用已有行（attempt 唯一约束），保留历史同款。"""
    item = (
        db.query(SkuImportItem)
        .filter_by(batch_id=batch.id, sku=sku)
        .order_by(SkuImportItem.attempt.desc())
        .first()
    )
    if item is not None:
        item.cluster_id = cluster.id
        item.product_name = product_name
        item.status = status
        item.error_message = error_message
    else:
        db.add(
            SkuImportItem(
                batch_id=batch.id,
                cluster_id=cluster.id,
                sku=sku,
                attempt=1,
                product_name=product_name,
                status=status,
                error_message=error_message,
            )
        )
    db.flush()


def _imported_item(cluster: Cluster, product_name: str) -> dict:
    return {
        "sku": cluster.sku,
        "productName": product_name,
        "status": "imported",
        "clusterId": str(cluster.id),
        "errorCode": None,
    }


def import_skus(
    db: Session,
    batch: Batch,
    skus: list[str],
    *,
    erp_token: str = "",
    mode: str = "organize",
) -> dict:
    clean = list(dict.fromkeys(str(s).strip() for s in skus if str(s).strip()))[: settings.catalog_max_skus_per_request]
    if not clean:
        return {"imported": 0, "failed": 0, "items": []}

    if not settings.catalog_query_url:
        return _import_plain(db, batch, clean, mode)

    try:
        products = CatalogClient(token=erp_token).fetch_products(clean)
    except CatalogAuthError:
        return {
            "imported": 0,
            "failed": len(clean),
            "items": [_fail_item(s, "login_expired", "登录已过期，请重新登录后导入") for s in clean],
        }
    except CatalogError:
        products = None

    imported = failed = 0
    items: list[dict] = []
    for sku in clean:
        product = products.get(sku) if products is not None else None
        product_name = str((product or {}).get("productName") or "").strip()[:200]
        cluster = db.query(Cluster).filter_by(batch_id=batch.id, sku=sku).first()

        if cluster is not None:
            if cluster.archived_at is not None:
                cluster.archived_at = None
            if product_name:
                filled = _backfill_name(cluster.product_name, product_name)
                if filled != cluster.product_name:
                    cluster.product_name = filled
                    cluster.name = filled
                    analysis = dict(cluster.analysis_snapshot or {})
                    analysis["product_name_source"] = "erp"
                    cluster.analysis_snapshot = analysis
            if mode == "auto":
                request_cluster_preparation(cluster, auto_generate=True)
            _record_import(db, batch, cluster, sku, cluster.product_name)
            imported += 1
            items.append(_imported_item(cluster, cluster.product_name))
            continue

        if products is None:
            failed += 1
            items.append(_fail_item(sku, "catalog_unavailable", "ERP 商品服务暂不可用"))
            continue
        if not product:
            failed += 1
            items.append(_fail_item(sku, "sku_not_found", "SKU 不存在或无可用商品图片"))
            continue
        try:
            data, content_type = download_catalog_image(product.get("pic"))
            normalized, forced_content_type, width, height = _validate_image(data, f"{sku}.jpg")
        except (CatalogError, UploadError):
            failed += 1
            items.append(_fail_item(sku, "catalog_image_invalid", "商品图片无法导入"))
            continue
        try:
            asset = _register_image_asset(db, batch, sku, normalized, forced_content_type, width, height)
        except Exception:
            failed += 1
            items.append(_fail_item(sku, "archive_failed", "商品图片归档失败"))
            continue
        cluster = Cluster(
            batch_id=batch.id,
            name=product_name or sku,
            sku=sku,
            product_name=product_name,
            analysis_snapshot={"product_name_source": "erp"},
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
        _record_import(db, batch, cluster, sku, product_name)
        imported += 1
        items.append(_imported_item(cluster, product_name))

    if batch.status in {"draft", "uploading"} or batch.last_import_mode != mode:
        batch.status = "organizing"
        batch.last_import_mode = mode
    db.commit()
    return {"imported": imported, "failed": failed, "items": items}


def _import_plain(db: Session, batch: Batch, skus: list[str], mode: str) -> dict:
    """未配置 catalog（本地开发）时退回旧行为：建 sku 同名空卡，不做 ERP 拉取。"""
    imported = failed = 0
    items: list[dict] = []
    for sku in skus:
        cluster = db.query(Cluster).filter_by(batch_id=batch.id, sku=sku).first()
        if cluster is not None:
            if cluster.archived_at is not None:
                cluster.archived_at = None
            if mode == "auto":
                request_cluster_preparation(cluster, auto_generate=True)
            _record_import(db, batch, cluster, sku, cluster.product_name)
            imported += 1
            items.append(_imported_item(cluster, cluster.product_name))
            continue
        cluster = Cluster(
            batch_id=batch.id,
            name=sku,
            sku=sku,
            product_name=sku,
            preparation_status="draft",
            preparation_stage="draft",
            preparation_total=7,
        )
        db.add(cluster)
        db.flush()
        if mode == "auto":
            request_cluster_preparation(cluster, auto_generate=True)
        _record_import(db, batch, cluster, sku, sku)
        imported += 1
        items.append(_imported_item(cluster, sku))
    if batch.status in {"draft", "uploading"} or batch.last_import_mode != mode:
        batch.status = "organizing"
        batch.last_import_mode = mode
    db.commit()
    return {"imported": imported, "failed": failed, "items": items}
