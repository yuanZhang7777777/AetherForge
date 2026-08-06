"""线上校验国家选择门：新建项目 market 为空 → PATCH 真实国家后 market 落库。"""
import sys
import time

import requests

BASE = sys.argv[1].rstrip("/")
USERNAME = sys.argv[2]
PASSWORD = sys.argv[3]

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
r = S.post(f"{BASE}/api/projects/", json={"name": "country-gate-check"})
assert r.status_code == 201, f"create failed: {r.status_code} {r.text[:200]}"
pid = r.json()["id"]
print("project:", pid)

snap = S.get(f"{BASE}/api/projects/{pid}/snapshot/").json()
print("market before:", repr(snap["market"]), "defaultConfig.market:", repr(snap["defaultConfig"]["market"]))
assert snap["market"] == "SEA" and snap["defaultConfig"]["market"] == "SEA", "new project defaults to generic SEA (gate triggers)"

r = S.patch(
    f"{BASE}/api/projects/{pid}/settings/",
    json={
        "platform": "shopee",
        "market": "TH",
        "seller_tier": "general",
        "size": "1:1",
        "resolution": "1k",
        "global_prompt": "",
        "ai_recognition_enabled": True,
    },
)
assert r.status_code == 200, f"settings failed: {r.status_code} {r.text[:300]}"
print("settings saved; ai_recognition_enabled:", r.json()["defaultConfig"]["aiRecognitionEnabled"])

snap = S.get(f"{BASE}/api/projects/{pid}/snapshot/").json()
print("market after:", repr(snap["market"]))
assert snap["market"] == "TH" and snap["defaultConfig"]["market"] == "TH", "market should persist after gate save"
print("\nCOUNTRY GATE CHECK OK")
