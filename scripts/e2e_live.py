"""线上 E2E：登录 → 建项目 → 上传 → 填商品名 → prepare(真实 DeepSeek) → READY → confirm → 导出。

用法：python scripts/e2e_live.py <base_url> <admin_password> [username]
"""
import io
import sys
import time

import requests
from PIL import Image

BASE = sys.argv[1].rstrip("/")
PASSWORD = sys.argv[2]
USERNAME = sys.argv[3] if len(sys.argv) > 3 else "admin"

S = requests.Session()
S.headers.update({"Accept": "application/json"})


def _get(url: str, **kwargs) -> requests.Response:
    for attempt in range(4):
        try:
            return S.get(url, timeout=30, **kwargs)
        except (requests.ConnectionError, requests.exceptions.ReadTimeout) as exc:
            if attempt == 3:
                raise
            print(f"  (retry {attempt + 1} on {type(exc).__name__})")
            time.sleep(2)
    raise RuntimeError("unreachable")


def csrf() -> str:
    return S.get(f"{BASE}/api/csrf/").json()["csrf_token"]


def login() -> None:
    token = csrf()
    r = S.post(
        f"{BASE}/login/",
        data={"csrfmiddlewaretoken": token, "username": USERNAME, "password": PASSWORD},
        allow_redirects=False,
    )
    assert r.status_code == 303, f"login failed: {r.status_code} {r.text[:200]}"
    print("login OK")


def create_project() -> str:
    r = S.post(
        f"{BASE}/api/projects/",
        json={"name": "live-e2e", "platform": "Shopee", "site": "TH", "market": "TH"},
    )
    assert r.status_code == 201, f"create failed: {r.status_code} {r.text[:200]}"
    pid = r.json()["id"]
    print("project:", pid)
    return pid


def upload(pid: str) -> tuple[str, str]:
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), (200, 120, 40)).save(buf, format="PNG")
    r = S.post(
        f"{BASE}/api/projects/{pid}/assets/",
        data={"mode": "organize"},
        files=[
            ("files", ("mug.png", buf.getvalue(), "image/png")),
            ("relative_paths", (None, "mug.png")),
        ],
    )
    assert r.status_code == 200, f"upload failed: {r.status_code} {r.text[:300]}"
    payload = r.json()
    print("upload:", payload["asset_count"], "imported", len(payload["imported"]))
    cluster = payload["imported"][0]["cluster_id"]
    return cluster, payload["imported"][0]["asset_id"]


def set_product_name(cluster_id: str) -> None:
    r = S.post(
        f"{BASE}/api/clusters/{cluster_id}/",
        json={"name": "保温咖啡杯", "product_name": "保温咖啡杯", "expected_version": 1},
    )
    assert r.status_code == 200, f"cluster update failed: {r.status_code} {r.text[:300]}"
    print("cluster updated:", r.json()["version"])


def prepare(pid: str, cluster_id: str) -> None:
    r = S.post(f"{BASE}/api/projects/{pid}/prepare/", json={"cluster_ids": [cluster_id]})
    assert r.status_code == 200, f"prepare failed: {r.status_code} {r.text[:300]}"
    print("prepare:", r.json()["items"])


def wait_ready(pid: str, cluster_id: str, timeout: int = 300) -> dict:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = _get(f"{BASE}/api/projects/{pid}/progress/")
        payload = r.json()
        item = next((c for c in payload["skus"] if c["id"] == cluster_id), None)
        if item is None:
            print("  progress payload keys:", list(payload.keys()))
            return {}
        status = item["preparationStatus"]
        stage = item.get("preparation", {}).get("stage", "")
        print(f"  [{int(time.monotonic()-start)}s] prep={status} stage={stage}")
        if status in {"ready", "failed", "blocked"}:
            return item
        time.sleep(5)
    raise TimeoutError("prepare did not finish in time")


def confirm(pid: str) -> None:
    r = S.post(f"{BASE}/api/projects/{pid}/confirm/", json={})
    assert r.status_code == 200, f"confirm failed: {r.status_code} {r.text[:300]}"
    print("confirm:", r.json().get("status"), "generations:", r.json().get("generation_count"))


def main() -> None:
    login()
    pid = create_project()
    cluster_id, asset_id = upload(pid)
    set_product_name(cluster_id)
    prepare(pid, cluster_id)
    item = wait_ready(pid, cluster_id)
    if item.get("preparationStatus") != "ready":
        print("preparation NOT ready:", item)
        sys.exit(1)
    confirm(pid)
    r = S.get(f"{BASE}/api/projects/{pid}/snapshot/")
    print("snapshot status:", r.json().get("status"))
    print("\nLIVE E2E OK (prepare -> READY + confirm queued)")


if __name__ == "__main__":
    main()
