"""拉取线上已完成出图，下载前若干张到本地供查看。"""
import sys
from pathlib import Path

import requests

BASE = sys.argv[1].rstrip("/")
USERNAME = sys.argv[2]
PASSWORD = sys.argv[3]
OUT = Path(sys.argv[4] if len(sys.argv) > 4 else "scripts/_results")
OUT.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({"Accept": "application/json"})


def login() -> None:
    token = S.get(f"{BASE}/api/csrf/").json()["csrf_token"]
    r = S.post(
        f"{BASE}/login/",
        data={"csrfmiddlewaretoken": token, "username": USERNAME, "password": PASSWORD},
        allow_redirects=False,
    )
    assert r.status_code == 303, f"login failed: {r.status_code} {r.text[:200]}"
    print("login OK")


login()
ws = S.get(f"{BASE}/api/workspace/snapshot/").json()
print("projects:", [(p["id"][:8], p["name"], p["status"]) for p in ws.get("projects", [])])

downloaded = 0
for proj in ws.get("projects", []):
    pid = proj["id"]
    snap = S.get(f"{BASE}/api/projects/{pid}/snapshot/").json()
    for sku in snap.get("skus", []):
        for out in sku.get("outputs", []):
            if out.get("status") != "completed" or not out.get("imageUrl"):
                continue
            data = S.get(f"{BASE}{out['imageUrl']}").content
            slot = out.get("slotOrder", "?")
            name = f"{proj['name'][:8]}_{sku.get('productName') or sku.get('name') or 'sku'}_{slot}.png"
            (OUT / name.replace("/", "_")).write_bytes(data)
            downloaded += 1
            if downloaded >= 12:
                print(f"saved {downloaded} images to {OUT}")
                sys.exit(0)
print(f"saved {downloaded} images to {OUT}")
