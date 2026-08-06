import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "../App";
import type { ProductSku, Project } from "../types";

const slots = ["hero", "angle", "detail_close_up", "real_life_use", "pain_point_solution", "size_and_material", "usage_steps", "lifestyle", "quality_and_trust"];
const product = (id: string, name: string): ProductSku => ({
  id,
  name,
  productNameSource: "manual" as const,
  sku: id,
  version: 1,
  assetIds: [`asset-${id}`],
  assets: [{ id: `asset-${id}`, name: `${id}-secret.jpg`, kind: "image", imageUrl: `/api/assets/asset-${id}/media/` }],
  facts: "可折叠",
  productFacts: "适合明亮桌面场景",
  identityLock: "保留蓝色外壳",
  identity: { product_name: name, confidence: 0.92, product_profile: { category: "桌面用品", primary_appearance: "蓝色折叠结构", shared_structure: ["折叠关节"] }, identity_lock: { must_not_change: ["蓝色外壳", "折叠关节"] } },
  brief: "柔和自然光",
  productStyle: "柔和自然光",
  preparationStatus: "preparing",
  preparation: { status: "preparing", stage: "N2", current: 2, total: 3, error: "" },
  generationProgress: { status: "idle", current: 0, total: 8 },
  overrides: { platform: null, market: null, sellerTier: null },
  effectiveConfig: { platform: "generic", market: "SEA", sellerTier: "general", size: "1:1", resolution: "1k", globalPrompt: "" },
  analysisSnapshot: {
    fact_ledger: {
      facts: [{ fact_id: "fact-1", statement: "蓝色外壳", fact_class: "observed", confidence: 0.9, evidence_refs: [], risk_level: "low", allowed_uses: ["visual_prompt"] }],
    },
  },
  prompts: slots.map((slot, index) => ({ slotOrder: index + 1, slot, text: `Prompt ${index + 1}` })),
  outputs: [],
});

const project: Project = {
  id: "project-1",
  name: "夏日上新",
  platform: "",
  market: "",
  template: "商品基础套图",
  size: "",
  resolution: "",
  configurationStatus: "required",
  defaultConfig: { platform: "", market: "", sellerTier: "general", size: "", resolution: "", globalPrompt: "" },
  status: "draft",
  updatedAt: "2026-07-31T00:00:00Z",
  assets: [
    { id: "asset-one", name: "one-secret.jpg", kind: "image", imageUrl: "/api/assets/asset-one/media/" },
    { id: "asset-two", name: "two-secret.jpg", kind: "image", imageUrl: "/api/assets/asset-two/media/" },
  ],
  skus: [product("one", "桌面灯"), product("two", "折叠椅")],
};

function response(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function renderApp(path = "/projects/project-1") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    ...render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
    ),
    queryClient,
  };
}

function stubFetch(options: { admin?: boolean; projectSnapshot?: typeof project; promptNodes?: Record<string, unknown>[] } = {}) {
  const currentProject = options.projectSnapshot ?? project;
  const promptNodes = options.promptNodes ?? [{
    id: "node-1",
    node_name: "N7.generic",
    version: "3.0.0",
    status: "retired",
    instruction: "严格检查九图 Prompt",
    user_message_template: "商品：{{ product }}",
    output_schema: { type: "object" },
    model: "deepseek-v4-pro",
    platform_scope: "generic",
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
  }];
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf" });
    if (url === "/api/current-user/") return response(200, { role: options.admin ? "admin" : "operator" });
    if (url === "/api/workspace/snapshot/") return response(200, { currentUser: { role: options.admin ? "admin" : "operator" }, projects: [currentProject] });
    if (url === "/api/admin/prompt-nodes/" && (!init?.method || init.method === "GET")) return options.admin ? response(200, { nodes: promptNodes }) : response(403, { error: "forbidden" });
    if (url === "/api/admin/prompt-nodes/" && init?.method === "POST") return response(201, promptNodes[0]);
    if (url === "/api/admin/prompt-nodes/publish/") return response(200, promptNodes[0]);
    return response(200, currentProject);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.stubEnv("VITE_DEMO_MODE", "false");
  stubFetch();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("renders the compact toolbar with confirmed defaults and searchable extra markets", async () => {
  const fetchMock = stubFetch();
  renderApp();

  expect(await screen.findByRole("heading", { name: "夏日上新" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "通用电商" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("项目国家")).toHaveDisplayValue("东南亚通用");
  expect(screen.getByLabelText("图片比例")).toHaveValue("1:1");
  expect(screen.getByLabelText("图片分辨率")).toHaveValue("1k");
  expect(screen.queryByRole("button", { name: "项目默认配置" })).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("项目国家"), { target: { value: "US" } });
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/settings/")).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/projects/project-1/settings/");
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ market: "US" });
});

test("keeps an unsaved project style when saving fails and the project snapshot refreshes", async () => {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf" });
    if (url === "/api/workspace/snapshot/") return response(200, { currentUser: { role: "operator" }, projects: [project] });
    if (url === "/api/projects/project-1/settings/") return response(503, { error: "保存失败" });
    return response(200, project);
  });
  vi.stubGlobal("fetch", fetchMock);
  const { queryClient } = renderApp();
  const style = await screen.findByLabelText("项目风格提示词");

  fireEvent.change(style, { target: { value: "本地未保存风格" } });
  fireEvent.blur(style);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/settings/")).toBe(true));

  await act(async () => {
    queryClient.setQueryData(["project", "project-1"], {
      ...project,
      defaultConfig: { ...project.defaultConfig, globalPrompt: "服务器轮询值" },
    });
  });
  expect(screen.getByLabelText("项目风格提示词")).toHaveValue("本地未保存风格");
});

test("prepares only selected products through the explicit preparation endpoint", async () => {
  const draftProject = {
    ...project,
    skus: project.skus.map((sku) => ({
      ...sku,
      preparationStatus: "draft",
      preparation: { status: "draft", stage: "draft", current: 0, total: 7, error: "" },
    })),
  };
  const fetchMock = stubFetch({ projectSnapshot: draftProject });
  renderApp();

  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 折叠椅" }));
  fireEvent.click(screen.getByRole("button", { name: "预备生成（1）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/prepare/")).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/projects/project-1/prepare/");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ cluster_ids: ["one"] });
});

test("does not requeue preparation while selected products already have active work", async () => {
  const fetchMock = stubFetch();
  renderApp();

  const prepareButton = await screen.findByRole("button", { name: "预备生成（2）" });
  expect(prepareButton).toBeDisabled();
  fireEvent.click(prepareButton);

  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/prepare/")).toBe(false);
  expect(screen.getByRole("button", { name: "暂停所选（2）" })).not.toBeDisabled();
});

test("keeps preparation click responsive while a card save is pending", async () => {
  const draftProject = {
    ...project,
    skus: project.skus.map((sku) => ({
      ...sku,
      preparationStatus: "draft",
      preparation: { status: "draft", stage: "draft", current: 0, total: 7, error: "" },
    })),
  };
  let releaseSave: (() => void) | undefined;
  const fetchMock = stubFetch({ projectSnapshot: draftProject });
  fetchMock.mockImplementation(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf" });
    if (url === "/api/projects/project-1/snapshot/") return response(200, draftProject);
    if (url === "/api/workspace/snapshot/") return response(200, { currentUser: { role: "operator" }, projects: [draftProject] });
    if (url === "/api/clusters/one/") {
      return new Promise((resolve) => {
        releaseSave = () => resolve(response(200, { id: "one", version: 2 }));
      });
    }
    if (url === "/api/projects/project-1/prepare/") return response(200, { items: [] });
    if (url === "/api/projects/project-1/progress/") return response(200, {
      id: project.id,
      status: "draft",
      updatedAt: "2026-07-31T00:00:00Z",
      skus: draftProject.skus.map((sku) => ({
        id: sku.id,
        preparationStatus: "draft",
        preparation: { status: "draft", stage: "draft", current: 0, total: 7, error: "" },
        generationProgress: { status: "idle", current: 0, completed: 0, active: 0, failed: 0, total: 0 },
        prompts: sku.prompts,
        outputs: [],
      })),
    });
    return response(200, project);
  });
  renderApp();

  const supplement = await screen.findByLabelText("补充信息 桌面灯");
  fireEvent.change(supplement, { target: { value: "新的补充信息" } });
  fireEvent.blur(supplement);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/clusters/one/")).toBe(true));

  fireEvent.click(screen.getByRole("button", { name: "预备生成（2）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/prepare/")).toBe(true));
  releaseSave?.();
});

test("pauses selected products from the floating action bar", async () => {
  const fetchMock = stubFetch();
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "暂停所选（2）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/pause/")).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/projects/project-1/pause/");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ cluster_ids: ["one", "two"] });
});

test("pauses one product from its card", async () => {
  const fetchMock = stubFetch();
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "暂停 桌面灯" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/pause/")).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/projects/project-1/pause/");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ cluster_ids: ["one"] });
});

test("shows the add-product panel inline with organize as the primary import action", async () => {
  renderApp();

  expect(await screen.findByRole("heading", { name: "夏日上新" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "添加商品" })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "添加商品" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("添加商品面板")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "图片/文件夹" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("ERP SKU")).toBeInTheDocument();
  expect(screen.getByLabelText("选择图片")).toHaveAttribute("multiple");
  expect(screen.getByLabelText("选择文件夹")).toHaveAttribute("webkitdirectory");
  expect(screen.getByRole("button", { name: "选择图片/文件夹" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "加载 SKU" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "导入后整理" })[0]).toHaveClass("primary-button");
  expect(screen.getAllByRole("button", { name: "导入并自动出图" })[0]).toHaveClass("secondary-button");
});

test("shows editable compact card fields and exact preparation progress without implementation codes", async () => {
  renderApp();

  expect(await screen.findByLabelText("商品名称 桌面灯")).toHaveValue("桌面灯");
  expect((screen.getByLabelText("补充信息 桌面灯") as HTMLTextAreaElement).value).toContain("适合明亮桌面场景");
  expect((screen.getByLabelText("补充信息 桌面灯") as HTMLTextAreaElement).value).toContain("保留蓝色外壳");
  expect(screen.getByLabelText("项目国家")).toBeInTheDocument();
  expect(screen.getByLabelText("商品平台 桌面灯")).toHaveDisplayValue("跟随项目");
  expect(screen.getByLabelText("商品国家 桌面灯")).toHaveDisplayValue("跟随项目");
  expect(screen.queryByLabelText("单品风格 桌面灯")).not.toBeInTheDocument();
  expect(screen.getAllByText("正在写提示词 · 2/3")).toHaveLength(2);
  expect(screen.getAllByRole("progressbar", { name: "预备生成进度" })).not.toHaveLength(0);
  expect(screen.getByLabelText("商品名称 桌面灯")).toHaveAttribute("placeholder", "可不填，预备生成时识别");
  expect(screen.getByRole("button", { name: "全选" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消全选" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "反选" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "暂停所选（2）" })).toBeInTheDocument();
  expect(screen.getByLabelText("滚动常驻生成动作")).toHaveTextContent("预备生成（2）");
  expect(screen.getByLabelText("滚动常驻生成动作")).toHaveTextContent("正式生成（2）");
  expect(screen.queryByText("单品风格（选填）")).not.toBeInTheDocument();
  expect(screen.queryByText("one-secret.jpg")).not.toBeInTheDocument();
  expect(screen.queryByText("generic")).not.toBeInTheDocument();
  expect(screen.queryByText("SEA")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("多图关系")).not.toBeInTheDocument();
});

test("shows the active preparation stage instead of queued when a stage is present", async () => {
  const stagedProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "pending",
      preparation: { status: "pending", stage: "N1", current: 0, total: 3, error: "" },
    }],
  };
  stubFetch({ projectSnapshot: stagedProject });
  renderApp();

  expect(await screen.findByText("正在识别商品 · 0/3")).toBeInTheDocument();
  expect(screen.queryByText(/预备排队中/)).not.toBeInTheDocument();
});

test("does not submit generation while selected products are still preparing", async () => {
  const preparingProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "preparing",
      preparation: { status: "preparing", stage: "N1", current: 0, total: 7, error: "" },
    }],
  };
  const fetchMock = stubFetch({ projectSnapshot: preparingProject });
  renderApp();

  const generateButton = await screen.findByRole("button", { name: "正式生成（1）" });
  expect(generateButton).toBeDisabled();
  fireEvent.click(generateButton);
  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/generate/")).toBe(false);
  expect(screen.getByRole("button", { name: "暂停所选（1）" })).not.toBeDisabled();
});

test("does not submit generation while selected products already have active output work", async () => {
  const runningProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "ready" as const,
      preparation: { status: "ready", stage: "N7", current: 7, total: 7, error: "" },
      generationProgress: { status: "running", current: 1, completed: 1, active: 2, failed: 0, total: 8 },
    }],
  };
  const fetchMock = stubFetch({ projectSnapshot: runningProject });
  renderApp();

  const generateButton = await screen.findByRole("button", { name: "正式生成（1）" });
  expect(generateButton).toBeDisabled();
  fireEvent.click(generateButton);

  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/generate/")).toBe(false);
  expect(screen.getByRole("button", { name: "暂停所选（1）" })).not.toBeDisabled();
});

test("does not offer pause when selected products have no active work", async () => {
  const idleProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "ready" as const,
      preparation: { status: "ready", stage: "N7", current: 7, total: 7, error: "" },
      generationProgress: { status: "completed", current: 8, completed: 8, active: 0, failed: 0, total: 8 },
    }],
  };
  const fetchMock = stubFetch({ projectSnapshot: idleProject });
  renderApp();

  const pauseButton = await screen.findByRole("button", { name: "暂停所选（1）" });
  expect(pauseButton).toBeDisabled();
  fireEvent.click(pauseButton);

  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/pause/")).toBe(false);
});

test("submits generation for the real editable prompt slots only", async () => {
  const vnSlots = [
    "Seller original product photo",
    "Standard white background product hero",
    "Product structure",
    "Product detail",
    "Usage",
    "User or scale",
    "Packaging or contents",
    "Local lifestyle",
    "Supplemental conversion",
  ];
  const readySku = {
    ...product("vn", "越南商品"),
    preparationStatus: "ready" as const,
    preparation: { status: "ready", stage: "N7", current: 7, total: 7, error: "" },
    prompts: vnSlots.map((slot, index) => ({ slotOrder: index + 1, slot, text: `Prompt ${index + 1}`, readOnly: index === 0 })),
  };
  const fetchMock = stubFetch({
    projectSnapshot: {
      ...project,
      skus: [readySku],
    },
  });
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "正式生成（1）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/generate/")).toBe(true));
  const generateCall = fetchMock.mock.calls.find(([url]) => String(url) === "/api/projects/project-1/generate/");
  expect(JSON.parse(String(generateCall?.[1]?.body))).toMatchObject({
    cluster_ids: ["vn"],
    slot_orders: [2, 3, 4, 5, 6, 7, 8, 9],
  });
});

test("does not load the full workspace snapshot on the new-project page", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/new");

  expect(await screen.findByRole("heading", { name: "创建出图项目" })).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/current-user/")).toBe(true);
  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/workspace/snapshot/")).toBe(false);
});

test("polls project progress instead of repeating the full active project snapshot", async () => {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf" });
    if (url === "/api/current-user/") return response(200, { role: "operator" });
    if (url === "/api/projects/project-1/snapshot/") return response(200, project);
    if (url === "/api/projects/project-1/progress/") return response(200, {
      id: project.id,
      status: "running",
      updatedAt: "2026-07-31T00:00:01Z",
      skus: project.skus.map((sku) => ({
        id: sku.id,
        preparationStatus: "preparing",
        preparation: { status: "preparing", stage: "N4", current: 4, total: 7, error: "" },
        generationProgress: { status: "idle", current: 0, completed: 0, active: 0, failed: 0, total: 0 },
        prompts: sku.prompts,
        outputs: [],
      })),
    });
    return response(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  renderApp();

  expect(await screen.findByRole("heading", { name: "夏日上新" })).toBeInTheDocument();
  vi.useFakeTimers();
  await act(async () => {
    vi.advanceTimersByTime(3100);
  });
  vi.useRealTimers();

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/projects/project-1/progress/")).toBe(true));
  expect(fetchMock.mock.calls.filter(([url]) => String(url) === "/api/projects/project-1/snapshot/")).toHaveLength(1);
});

test("shows product name source only for AI recognition and ERP", async () => {
  const sourceProject = {
    ...project,
    skus: [
      { ...product("ai", "AI 商品"), productNameSource: "ai" as const },
      { ...product("erp", "ERP 商品"), productNameSource: "erp" as const },
      { ...product("manual", "手工商品"), productNameSource: "manual" as const },
      { ...product("blank", "空来源商品"), productNameSource: "blank" as const },
    ],
  };
  stubFetch({ projectSnapshot: sourceProject });
  renderApp();

  expect(within(await screen.findByRole("group", { name: "AI 商品 商品卡片（可拖拽合并）" })).getByText("AI 识别，可修改")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "ERP 商品 商品卡片（可拖拽合并）" })).getByText("来自 ERP")).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "手工商品 商品卡片（可拖拽合并）" })).queryByText(/AI 识别|来自 ERP/)).not.toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "空来源商品 商品卡片（可拖拽合并）" })).queryByText(/AI 识别|来自 ERP/)).not.toBeInTheDocument();
});

test("reports mixed generation failures without per-product market overrides", async () => {
  const failedProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "ready",
      preparation: { status: "ready", stage: "N7", current: 7, total: 7, error: "" },
      generationProgress: { status: "completed", current: 6, completed: 6, active: 0, failed: 2, total: 8 },
    }],
  };
  const fetchMock = stubFetch({ projectSnapshot: failedProject });
  renderApp();

  await screen.findByLabelText("商品名称 桌面灯");
  expect(screen.getByText(/有 2 张失败/)).toHaveTextContent("出图已结束 · 6/8 · 有 2 张失败");
  expect(screen.queryByText(/预备完成/)).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/clusters/one/")).toBe(false);
});

test("shows active generation progress without a 0/0 denominator", async () => {
  const runningProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "ready",
      preparation: { status: "ready", stage: "N7", current: 7, total: 7, error: "" },
      generationProgress: { status: "running", current: 0, completed: 0, active: 1, failed: 0, total: 0 },
    }],
  };
  stubFetch({ projectSnapshot: runningProject });
  renderApp();

  await screen.findByLabelText("商品名称 桌面灯");
  expect(screen.getByText("出图中 · 0/9")).toBeInTheDocument();
  expect(screen.queryByText(/0\/0/)).not.toBeInTheDocument();
});

test("hides technical preparation errors from operators", async () => {
  const failedProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "failed",
      preparation: { status: "failed", stage: "failed", current: 0, total: 7, error: "evidence_refs contains an unknown evidence reference" },
    }],
  };
  stubFetch({ projectSnapshot: failedProject });
  renderApp();

  expect(await screen.findByText(/预备未完成 · 提示词生成失败，请重试预备生成/)).toBeInTheDocument();
  expect(screen.queryByText(/evidence_refs/)).not.toBeInTheDocument();
});

test("shows specific model preparation errors without technical details", async () => {
  const failedProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "failed",
      preparation: { status: "failed", stage: "failed", current: 0, total: 7, error: "模型服务响应超时，请重试预备生成" },
    }],
  };
  stubFetch({ projectSnapshot: failedProject });
  renderApp();

  expect(await screen.findByText(/预备未完成 · 模型服务响应超时，请重试预备生成/)).toBeInTheDocument();
});

test("shows write-prompt progress without source-photo overcounting", async () => {
  const preparingProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      preparationStatus: "preparing",
      preparation: { status: "preparing", stage: "N2", current: 2, total: 3, error: "" },
    }],
  };
  stubFetch({ projectSnapshot: preparingProject });
  renderApp();

  expect(await screen.findByText("正在写提示词 · 2/3")).toBeInTheDocument();
  expect(screen.queryByText(/正在生成 1\+8 提示词/)).not.toBeInTheDocument();
});

test("shows AI-recognized English product info as Chinese operator text", async () => {
  stubFetch({
    projectSnapshot: {
      ...project,
      skus: [{
        ...product("english", "Copper-bowl wooden-handled cutlery"),
        productNameSource: "ai",
        facts: "visible wooden-handled spoons with tray; tray material resembles pressed pulp/cardboard",
        productFacts: "visible wooden-handled spoons with tray; tray material resembles pressed pulp/cardboard",
        identityLock: "wooden handled cutlery; tray set",
      }],
    },
  });
  renderApp();

  const card = await screen.findByRole("group", { name: /木柄餐具套装 商品卡片/ });
  expect(within(card).getByLabelText("商品名称 木柄餐具套装")).toHaveValue("木柄餐具套装");
  expect((within(card).getByLabelText("补充信息 木柄餐具套装") as HTMLTextAreaElement).value).toContain("木柄餐具套装");
  expect(within(card).queryByDisplayValue(/Copper-bowl|visible wooden/i)).not.toBeInTheDocument();
});

test("shows mixed English recognized plush identity as Chinese operator text", async () => {
  stubFetch({
    projectSnapshot: {
      ...project,
      skus: [{
        ...product("plush", "Yellow plush toy"),
        productNameSource: "ai",
        facts: "Yellow plush toy, round black eyes, plush texture\nMain appearance:\nStyle/Color: Yellow plush toy\nStyle/Requirements:\nIdentity maintained: yellow plush暗黑风格",
        productFacts: "Yellow plush toy, round black eyes, plush texture\nMain appearance:\nStyle/Color: Yellow plush toy\nStyle/Requirements:\nIdentity maintained: yellow plush暗黑风格",
        identityLock: "yellow plush暗黑风格",
        identity: {
          product_name: "Yellow plush toy",
          confidence: 0.9,
          product_profile: { category: "plush toy", primary_appearance: "Yellow plush toy, round black eyes, plush texture", shared_structure: ["plush texture", "round black eyes"] },
          identity_lock: { must_not_change: ["yellow plush", "round black eyes"] },
          target_appearances: [],
        },
      }],
    },
  });
  renderApp();

  const card = await screen.findByRole("group", { name: /黄色毛绒玩偶 商品卡片/ });
  const supplement = within(card).getByLabelText("补充信息 黄色毛绒玩偶") as HTMLTextAreaElement;
  expect(supplement.value).toContain("黄色毛绒玩偶");
  expect(supplement.value).toContain("圆形黑眼睛");
  expect(supplement.value).toContain("毛绒质感");
  expect(supplement.value).toContain("暗黑风格");
  expect(supplement.value).not.toMatch(/Yellow plush|Main appearance|Style\/Color|Identity maintained/i);
});

test("fills an empty product name from a later AI identity snapshot without overwriting edited supplement", async () => {
  const blankProject = {
    ...project,
    skus: [{
      ...product("blank", ""),
      name: "",
      productFacts: "",
      facts: "",
      identity: undefined,
      productNameSource: "blank" as const,
    }],
  };
  stubFetch({ projectSnapshot: blankProject });
  const { queryClient } = renderApp();

  const supplement = await screen.findByLabelText("补充信息 未命名商品");
  fireEvent.change(supplement, { target: { value: "人工补充不要覆盖" } });
  await act(async () => {
    queryClient.setQueryData(["project", "project-1"], {
      ...blankProject,
      skus: [{
        ...blankProject.skus[0],
        name: "Yellow plush toy",
        productNameSource: "ai" as const,
        facts: "Yellow plush toy, round black eyes",
        productFacts: "Yellow plush toy, round black eyes",
        identity: {
          product_name: "Yellow plush toy",
          confidence: 0.92,
          product_profile: { category: "plush toy", primary_appearance: "Yellow plush toy, round black eyes" },
        },
        version: 2,
      }],
    });
  });

  expect(await screen.findByLabelText("商品名称 黄色毛绒玩偶")).toHaveValue("黄色毛绒玩偶");
  expect(screen.getByLabelText("补充信息 黄色毛绒玩偶")).toHaveValue("人工补充不要覆盖");
});

test("opens one product in a fixed side panel and consumes the first outside click", async () => {
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "桌面灯 详情" }));
  expect(screen.getByRole("dialog", { name: "桌面灯 商品详情" })).toBeInTheDocument();
  expect(screen.getByText("商品信息与生成提示词")).toBeInTheDocument();
  expect(screen.queryByText("商品信息与 1+8 提示词")).not.toBeInTheDocument();
  expect((screen.getAllByLabelText("补充信息 桌面灯")[0] as HTMLTextAreaElement).value).toContain("适合明亮桌面场景");
  expect(screen.queryByLabelText("商品身份")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("主要外观")).not.toBeInTheDocument();
  expect(screen.getByText("9 张生成提示词")).toBeInTheDocument();
  expect(screen.getByText("01 标准白底产品图提示词")).toBeInTheDocument();
  expect(screen.getByText("02 核心卖点图提示词")).toBeInTheDocument();
  expect(screen.queryByText("1+8 输出提示词")).not.toBeInTheDocument();
  expect(screen.queryByText(/第 1 张输出图提示词/)).not.toBeInTheDocument();

  const dialog = screen.getByRole("dialog", { name: "桌面灯 商品详情" });
  fireEvent.pointerDown(dialog);
  fireEvent.click(document.body);
  expect(screen.getByRole("dialog", { name: "桌面灯 商品详情" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "折叠椅 详情" }));
  expect(screen.queryByRole("dialog", { name: "桌面灯 商品详情" })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "折叠椅 商品详情" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "折叠椅 详情" }));
  expect(screen.getByRole("dialog", { name: "折叠椅 商品详情" })).toBeInTheDocument();
});

test("labels Shopee VN source-photo slots without a duplicate white-background title", async () => {
  const vnSlots = [
    "Seller original product photo",
    "Standard white background product hero",
    "Product structure",
    "Product detail",
    "Usage",
    "User or scale",
    "Packaging or contents",
    "Local lifestyle",
    "Supplemental conversion",
  ];
  stubFetch({
    projectSnapshot: {
      ...project,
      platform: "shopee",
      market: "VN",
      defaultConfig: { platform: "shopee", market: "VN", sellerTier: "general", size: "1:1", resolution: "1k", globalPrompt: "" },
      skus: [{
        ...product("vn", "越南商品"),
        prompts: vnSlots.map((slot, index) => ({ slotOrder: index + 1, slot, text: "", readOnly: index === 0 })),
      }],
    },
  });
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "越南商品 详情" }));

  expect(screen.getByText("8 张生成提示词")).toBeInTheDocument();
  expect(screen.queryByText("01 原始商品图提示词")).not.toBeInTheDocument();
  expect(screen.getByText("01 标准白底产品图提示词")).toBeInTheDocument();
  expect(screen.getByText("02 商品结构图提示词")).toBeInTheDocument();
  expect(screen.getByText("07 本地生活方式图提示词")).toBeInTheDocument();
  expect(screen.queryByText("1+8 输出提示词")).not.toBeInTheDocument();
});

test("hides Prompt Center from operators and exposes the Chinese administrator page", async () => {
  renderApp("/");
  expect(await screen.findByRole("heading", { name: "工作台" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Prompt 管理中心" })).not.toBeInTheDocument();
  cleanup();

  stubFetch({ admin: true });
  renderApp("/admin/prompt-center");
  expect(await screen.findByRole("heading", { name: "Prompt 管理中心" })).toBeInTheDocument();
  expect(screen.getByText("严格检查九图 Prompt")).toBeInTheDocument();
  expect(screen.getByText(/deepseek-v4-pro/)).toHaveTextContent("deepseek-v4-pro");
  expect(screen.getByText(/deepseek-v4-pro/)).toHaveTextContent("通用电商");
  expect(screen.getByRole("button", { name: "发布此版本" })).toBeInTheDocument();
});

test("does not invent model or platform scope when Prompt Center metadata is absent", async () => {
  const nodeWithoutOptionalMetadata = {
    id: "node-2",
    node_name: "N1.generic",
    version: "3.0.0",
    status: "draft",
    instruction: "观察素材",
    user_message_template: "",
    output_schema: { type: "object" },
    model: null,
    platform_scope: null,
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
  };
  stubFetch({ admin: true, promptNodes: [nodeWithoutOptionalMetadata] });
  renderApp("/admin/prompt-center");

  expect(await screen.findByText("观察素材")).toBeInTheDocument();
  expect(screen.queryByText(/模型由运行时配置/)).not.toBeInTheDocument();
  expect(screen.queryByText(/共享范围/)).not.toBeInTheDocument();
});

test("creates drafts and publishes exact historical versions through the frozen admin API", async () => {
  const fetchMock = stubFetch({ admin: true });
  renderApp("/admin/prompt-center");

  fireEvent.click(await screen.findByRole("button", { name: "新建草稿" }));
  fireEvent.change(screen.getByLabelText("节点名称"), { target: { value: "N7.shopee" } });
  fireEvent.change(screen.getByLabelText("版本"), { target: { value: "3.0.1" } });
  fireEvent.change(screen.getByLabelText("系统 Prompt"), { target: { value: "检查 Shopee 九图" } });
  fireEvent.change(screen.getByLabelText("用户消息模板"), { target: { value: "商品：{{ product }}" } });
  fireEvent.change(screen.getByLabelText("输出 Schema"), { target: { value: "{\"type\":\"object\"}" } });
  fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/admin/prompt-nodes/" && init?.method === "POST")).toBe(true));
  const draftCall = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/admin/prompt-nodes/" && init?.method === "POST");
  expect(JSON.parse(String(draftCall?.[1]?.body))).toEqual({
    node_name: "N7.shopee",
    version: "3.0.1",
    instruction: "检查 Shopee 九图",
    user_message_template: "商品：{{ product }}",
    output_schema: { type: "object" },
  });

  fireEvent.click(screen.getByRole("button", { name: "发布此版本" }));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/admin/prompt-nodes/publish/")).toBe(true));
  const publishCall = fetchMock.mock.calls.find(([url]) => String(url) === "/api/admin/prompt-nodes/publish/");
  expect(JSON.parse(String(publishCall?.[1]?.body))).toEqual({ node_name: "N7.generic", version: "3.0.0" });
});
