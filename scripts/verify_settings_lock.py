"""线上验证：改平台/国家 → 集群失效重预备 + confirm/generate 被拦截。"""
import sys
import time

import requests

BASE = sys.argv[1].rstrip("/")
USERNAME = sys.argv[2]
PASSWORD = sys.argv[3]

S = requests.Session()
S.headers.update({"Accept": "application/json"})


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


def auth_headers() -> dict:
    return {"X-CSRFToken": csrf()}


login()
P = lambda: S.get(f"{BASE}/api/workspace/snapshot/").json()

# 建项目 + sku-import（auto 触发预备，需等 READY）
pid = S.post(f"{BASE}/api/projects/", json={"name": "settings-lock-verify"}, headers=auth_headers()).json()["id"]
print("project:", pid[:8])
r = S.post(
    f"{BASE}/api/projects/{pid}/sku-import/",
    json={"skus": ["settings-lock-test-sku"], "mode": "auto"},
    headers=auth_headers(),
).json()
print("sku-import:", r)

def cluster_state() -> dict:
    snap = S.get(f"{BASE}/api/projects/{pid}/snapshot/").json()
    sku = snap["skus"][0]
    return {"status": sku.get("preparationStatus"), "stage": sku.get("preparationStage"), "market": snap.get("market"), "id": sku["id"]}

# 等 prepare 到 READY
state = cluster_state()
deadline = time.time() + 120
while state["status"] != "ready" and time.time() < deadline:
    time.sleep(2)
    state = cluster_state()
print("after prepare:", state)
assert state["status"] == "ready", "prepare 未到 ready"

# 改市场 → 集群应失效为 draft
orig_market = state["market"]
new_market = "VN" if orig_market != "VN" else "ID"
settings = {
    "platform": "shopee",
    "market": new_market,
    "sellerTier": "general",
    "size": "1:1",
    "resolution": "1k",
    "globalPrompt": "",
    "aiRecognitionEnabled": False,
}
S.patch(f"{BASE}/api/projects/{pid}/settings/", json=settings, headers=auth_headers()).json()
state = cluster_state()
print("after market change:", state)
assert state["status"] == "draft", f"预期 draft，实际 {state['status']}"

# generate 应被拦截
g = S.post(
    f"{BASE}/api/projects/{pid}/generate/",
    json={"cluster_ids": [state["id"]], "slot_orders": []},
    headers=auth_headers(),
).json()
print("generate items:", g["items"])
assert g["items"] and g["items"][0].get("code") == "preparation_stale", "generate 未被拦截"
print("OK: 改市场后集群失效 draft，generate 返回 preparation_stale")
