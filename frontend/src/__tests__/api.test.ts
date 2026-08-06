import { afterEach, expect, test, vi } from "vitest";

import {
  createProject,
  exportProject,
  generateProject,
  importSkus,
  loadWorkspace,
  logoutUser,
  mergeAsset,
  preflightProject,
  regenerateGeneration,
  reviseGeneration,
  submitReview,
  updateProjectSettings,
  uploadAssets,
} from "../api";

afterEach(() => vi.unstubAllGlobals());

const project = {
  id: "project-1",
  name: "新品",
  platform: "shopee",
  market: "SG",
  template: "商品基础套图",
  size: "1:1",
  status: "draft",
  updatedAt: "2026-07-29T00:00:00Z",
  assets: [],
  skus: [],
};

function response(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("obtains a CSRF token from the same-origin bootstrap endpoint before creating a project", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf_token: "csrf-for-test" }) })
    .mockResolvedValueOnce(response(201, project));
  vi.stubGlobal("fetch", fetchMock);

  await createProject({ name: "新品", platform: "Shopee", market: "SG", template: "商品基础套图", size: "1:1 · 1K" });

  expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/csrf/", { credentials: "same-origin" });
  expect(fetchMock.mock.calls[1][1].headers.get("X-CSRFToken")).toBe("csrf-for-test");
});

test("creates a project with its name only so market setup happens in the workbench", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf_token: "csrf-for-test" }) })
    .mockResolvedValueOnce(response(201, project));
  vi.stubGlobal("fetch", fetchMock);

  await createProject({ name: "新品" });

  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ name: "新品" });
});

test("logs out with a CSRF-protected same-origin POST", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      redirected: true,
      url: "http://localhost:3000/login/",
    });
  vi.stubGlobal("fetch", fetchMock);

  await expect(logoutUser()).resolves.toBeUndefined();

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/logout/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
  expect(fetchMock.mock.calls[1][1].headers.get("X-CSRFToken")).toBe("csrf-for-test");
});

test("treats an expired session during logout CSRF bootstrap as logged out", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce({
    ok: true,
    status: 200,
    redirected: true,
    url: "http://localhost:3000/login/",
    json: async () => ({}),
  });
  vi.stubGlobal("fetch", fetchMock);

  await expect(logoutUser()).resolves.toBeUndefined();

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith("/api/csrf/", { credentials: "same-origin" });
});

test("treats an expired logout POST as logged out", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(403, { error: "CSRF Failed" }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(logoutUser()).resolves.toBeUndefined();
});

test("rejects a logout response that did not redirect to login", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, {}));
  vi.stubGlobal("fetch", fetchMock);

  await expect(logoutUser()).rejects.toMatchObject({ status: 200 });
});

test("keeps logout failures visible to the caller", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(500, { error: "logout unavailable" }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(logoutUser()).rejects.toMatchObject({ status: 500, message: "logout unavailable" });
});

test("canonicalizes market codes to uppercase without restricting unlisted countries", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf_token: "csrf-for-test" }) })
    .mockResolvedValueOnce(response(201, project));
  vi.stubGlobal("fetch", fetchMock);

  await updateProjectSettings("project-1", {
    platform: "shopee", market: "br", sellerTier: "general", size: "1:1", resolution: "1k", globalPrompt: "",
  });

  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ market: "BR" });
  expect(fetchMock.mock.calls[1][0]).toBe("/api/projects/project-1/settings/");
  expect(fetchMock.mock.calls[1][1].method).toBe("PATCH");
});

test("does not turn a 403 workspace response into mock data outside explicit demo mode", async () => {
  vi.stubEnv("VITE_DEMO_MODE", "false");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(403, { error: "forbidden" })));

  await expect(loadWorkspace()).rejects.toMatchObject({ status: 403, message: "forbidden" });
});

test("treats a redirected HTML login page as an authentication error instead of JSON", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    redirected: true,
    headers: new Headers({ "content-type": "text/html; charset=utf-8" }),
    json: async () => "<html>login</html>",
  }));

  await expect(loadWorkspace()).rejects.toMatchObject({
    status: 401,
    message: "登录已失效或需修改密码",
  });
});

test("treats a final login URL as an authentication error even when the redirect flag is unavailable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    redirected: false,
    url: "https://platform.example/accounts/login/?next=/api/workspace/snapshot/",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({ projects: [] }),
  }));

  await expect(loadWorkspace()).rejects.toMatchObject({
    status: 401,
    message: "登录已失效或需修改密码",
  });
});

test("keeps the original status for a non-login HTML error response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false,
    status: 405,
    redirected: false,
    url: "https://platform.example/api/workspace/snapshot/",
    headers: new Headers({ "content-type": "text/html" }),
    json: async () => { throw new Error("HTML is not JSON"); },
  }));

  await expect(loadWorkspace()).rejects.toMatchObject({
    status: 405,
    message: "请求失败（405）",
    authRequired: false,
  });
});

test("posts preflight with CSRF and discards quota fields returned by the server", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, {
      cluster_count: 1,
      slot_count: 2,
      generation_count: 2,
      blocking_errors: [],
      org_remaining: 99,
      user_remaining: 9,
    }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(preflightProject("project-1")).resolves.toEqual({
    cluster_count: 1,
    slot_count: 2,
    generation_count: 2,
    blocking_errors: [],
  });
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/projects/project-1/preflight/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
  expect(fetchMock.mock.calls[1][1].headers.get("X-CSRFToken")).toBe("csrf-for-test");
});

test("chunks uploads at 50 files and combines per-file results", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, {
      asset_count: 49,
      imported: Array.from({ length: 49 }, (_, index) => ({
        filename: `image-${index}.png`,
        asset_id: `asset-${index}`,
        cluster_id: `cluster-${index}`,
      })),
      rejected: [{ filename: "image-49.png", code: "unsupported_format", message: "不支持" }],
    }))
    .mockResolvedValueOnce(response(200, {
      asset_count: 1,
      imported: [{ filename: "image-50.png", asset_id: "asset-50", cluster_id: "cluster-50" }],
      rejected: [],
    }));
  vi.stubGlobal("fetch", fetchMock);
  const files = Array.from({ length: 51 }, (_, index) => new File(["image"], `image-${index}.png`, { type: "image/png" }));

  const result = await uploadAssets("project-1", files, "organize");

  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect((fetchMock.mock.calls[1][1].body as FormData).getAll("files")).toHaveLength(50);
  expect((fetchMock.mock.calls[2][1].body as FormData).getAll("files")).toHaveLength(1);
  expect(result.asset_count).toBe(50);
  expect(result.imported).toHaveLength(50);
  expect(result.rejected).toEqual([{ filename: "image-49.png", code: "unsupported_format", message: "不支持" }]);
});

test("keeps successful upload chunks when a later chunk is interrupted", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, {
      asset_count: 50,
      imported: Array.from({ length: 50 }, (_, index) => ({
        filename: `image-${String(index).padStart(2, "0")}.png`,
        asset_id: `asset-${index}`,
        cluster_id: `cluster-${index}`,
      })),
      rejected: [],
    }))
    .mockRejectedValueOnce(new Error("network down"));
  vi.stubGlobal("fetch", fetchMock);
  const files = Array.from({ length: 51 }, (_, index) => new File(["image"], `image-${String(index).padStart(2, "0")}.png`, { type: "image/png" }));

  const result = await uploadAssets("project-1", files, "organize");

  expect(result.asset_count).toBe(50);
  expect(result.imported).toHaveLength(50);
  expect(result.rejected).toEqual([{
    filename: "image-50.png",
    code: "upload_interrupted",
    message: "上传中断，请重试剩余文件",
  }]);
});

test("posts browser relative paths and TXT files before images", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { asset_count: 2, imported: [], rejected: [] }));
  vi.stubGlobal("fetch", fetchMock);
  const image = new File(["image"], "front.png", { type: "image/png" });
  const txt = new File(["style"], "style.txt", { type: "text/plain" });
  Object.defineProperty(image, "webkitRelativePath", { value: "lamp/angles/front.png" });
  Object.defineProperty(txt, "webkitRelativePath", { value: "lamp/style.txt" });

  await uploadAssets("project-1", [image, txt], "organize");

  const form = fetchMock.mock.calls[1][1].body as FormData;
  expect(form.get("mode")).toBe("organize");
  expect(form.getAll("relative_paths")).toEqual(["lamp/style.txt", "lamp/angles/front.png"]);
});

test("imports ERP SKUs with the chosen dual-speed mode", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { imported: 2, failed: 0, items: [] }));
  vi.stubGlobal("fetch", fetchMock);

  await importSkus("project-1", ["SKU-1", "SKU-2"], "auto");

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/projects/project-1/sku-import/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ skus: ["SKU-1", "SKU-2"], mode: "auto" });
});

test("starts generation for explicit product and slot selections", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { created: 9 }));
  vi.stubGlobal("fetch", fetchMock);

  await generateProject("project-1", { clusterIds: ["cluster-1"], slotOrders: [1, 2, 3] });

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/projects/project-1/generate/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ cluster_ids: ["cluster-1"], slot_orders: [1, 2, 3] });
});

test("requests a fresh generation version through the regenerate endpoint", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { generation: { id: "generation-2" } }));
  vi.stubGlobal("fetch", fetchMock);

  await regenerateGeneration("generation-1");

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/generations/generation-1/regenerate/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
});

test("submits revision annotations without using the old review decision contract", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { generation: { id: "generation-2" } }));
  vi.stubGlobal("fetch", fetchMock);

  await reviseGeneration("generation-1", {
    issue_tags: ["identity"],
    description: "Keep the lamp head shape",
    annotations: [{ kind: "circle", rect: [0.1, 0.2, 0.3, 0.4], color: "#ff0000", width: 2 }],
  });

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/generations/generation-1/revise/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    issue_tags: ["identity"],
    description: "Keep the lamp head shape",
    annotations: [{ kind: "circle", rect: [0.1, 0.2, 0.3, 0.4], color: "#ff0000", width: 2 }],
  });
});

test("exports only explicitly selected generations through a POST body", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce({ ok: true, status: 200, blob: async () => new Blob(["zip"]) });
  vi.stubGlobal("fetch", fetchMock);

  await exportProject("project-1", ["generation-1", "generation-2"]);

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/projects/project-1/export/",
    expect.objectContaining({ credentials: "same-origin", method: "POST" }),
  );
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ generation_ids: ["generation-1", "generation-2"] });
});

test("merges an asset through the versioned Django cluster endpoint", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { id: "sku-target", version: 4 }));
  vi.stubGlobal("fetch", fetchMock);

  await mergeAsset("sku-target", "asset-side-angle", 3);

  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/clusters/sku-target/merge/",
    expect.objectContaining({ credentials: "same-origin" }),
  );
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ asset_id: "asset-side-angle", expected_version: 3 });
});

test("submits normalized review annotations with the chosen decision", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { generation: { id: "generation-1", attempt: 2 } }));
  vi.stubGlobal("fetch", fetchMock);

  await submitReview("generation-1", {
    decision: "changes_requested",
    issue_tags: ["logo"],
    description: "Logo needs correction",
    annotations: [{ kind: "circle", rect: [0.1, 0.2, 0.3, 0.4], color: "#ff0000", width: 2 }],
  });

  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    decision: "changes_requested",
    issue_tags: ["logo"],
    description: "Logo needs correction",
    annotations: [{ kind: "circle", rect: [0.1, 0.2, 0.3, 0.4], color: "#ff0000", width: 2 }],
  });
});

test("submits an acceptance decision to the same real review endpoint", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(200, { generation: { id: "generation-1", attempt: 1 } }));
  vi.stubGlobal("fetch", fetchMock);

  await submitReview("generation-1", { decision: "accept", issue_tags: [], description: "", annotations: [] });

  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ decision: "accept" });
});

test("keeps a review failure visible to the caller instead of manufacturing success", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response(200, { csrf_token: "csrf-for-test" }))
    .mockResolvedValueOnce(response(500, { error: "review unavailable" }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(submitReview("generation-1", { decision: "accept", issue_tags: [], description: "", annotations: [] }))
    .rejects.toMatchObject({ status: 500, message: "review unavailable" });
});
