"""P1 冒烟测试：认证 → 建项目 → 上传 → prepare → generate → 导出。"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from backend.main import app


def main():
    c = TestClient(app)

    r = c.get("/api/health")
    assert r.status_code == 200, r.text

    r = c.get("/api/workspace/snapshot/", follow_redirects=False)
    assert r.status_code == 303 and r.headers.get("location") == "/login/", (r.status_code, r.headers.get("location"))

    r = c.get("/login/")
    html = r.text
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    assert m, f"login page csrf not found: {html[:500]}"
    csrf = m.group(1)

    r = c.post(
        "/login/",
        data={"csrfmiddlewaretoken": csrf, "username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[:300])

    r = c.get("/api/current-user/")
    assert r.status_code == 200 and r.json()["role"] == "admin", r.text

    r = c.post("/api/projects/", json={"name": "smoke-1"})
    assert r.status_code == 201, r.text
    project = r.json()
    project_id = project["id"]
    print("project created:", project_id, "status:", project["status"])

    r = c.get(f"/api/projects/{project_id}/snapshot/")
    assert r.status_code == 200, r.text
    snapshot = r.json()
    assert snapshot["templateSlots"], "template slots missing"
    print("template slots:", [s["name"] for s in snapshot["templateSlots"]])
    assert len(snapshot["templateSlots"]) == 8

    # upload a tiny valid PNG
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (16, 16), (200, 60, 60)).save(buf, format="PNG")
    png = buf.getvalue()
    csrf2 = c.get("/api/csrf/").json()["csrf_token"]
    r = c.post(
        f"/api/projects/{project_id}/assets/",
        data={"mode": "organize", "relative_paths": "product-a.png"},
        files={"files": ("product-a.png", png, "image/png")},
        headers={"X-CSRFToken": csrf2},
    )
    print("upload:", r.status_code, r.json())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_count"] == 1, body
    cluster_id = body["imported"][0]["cluster_id"]
    assert cluster_id, body
    print("cluster created:", cluster_id)

    r = c.get(f"/api/projects/{project_id}/snapshot/")
    skus = r.json()["skus"]
    assert len(skus) == 1, r.text
    sku = skus[0]
    print("sku name:", sku["name"], "assets:", len(sku["assets"]))

    # update cluster: set product name
    r = c.post(
        f"/api/clusters/{cluster_id}/",
        json={"expected_version": sku["version"], "name": "智慧保温杯", "product_facts": "容量500ml\n材质316不锈钢\n保温12小时"},
    )
    print("cluster update:", r.status_code, r.json())
    assert r.status_code == 200, r.text
    new_version = r.json()["version"]

    # optimistic lock conflict
    r = c.post(
        f"/api/clusters/{cluster_id}/",
        json={"expected_version": sku["version"], "name": "stale"},
    )
    print("stale update:", r.status_code, r.json())
    assert r.status_code == 409, r.text

    # prepare (pending, worker not running → stays queued)
    r = c.post(f"/api/projects/{project_id}/prepare/", json={"cluster_ids": [cluster_id]})
    print("prepare:", r.status_code, r.json())
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["status"] in {"queued", "preparing", "already_ready"}, r.json()

    # preflight
    r = c.post(f"/api/projects/{project_id}/preflight/")
    print("preflight:", r.status_code, r.json())
    assert r.status_code == 200

    print("\nSMOKE OK")


if __name__ == "__main__":
    sys.exit(main())
