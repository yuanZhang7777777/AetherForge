import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";

const slotNames = [
  "标准白底产品图",
  "核心卖点图",
  "细节特写图",
  "功能说明图",
  "真实使用场景图",
  "模特/比例图",
  "尺寸/包装/包含物图",
  "平台转化营销图",
];

const backendOutputSlotNames = [
  "Standard white-background product hero",
  "Key benefit",
  "Product detail",
  "Function",
  "Usage",
  "Model or scale",
  "Size, packaging, or contents",
  "Marketplace conversion",
];

const outputs = backendOutputSlotNames.flatMap((slot, index) => {
  const order = index + 1;
  const base = {
    id: `generation-${order}`,
    name: slot,
    slot,
    slotId: `slot-${order}`,
    slotOrder: order,
    attempt: 1,
    version: 1,
    status: "completed",
    reviewStatus: "accepted",
    imageUrl: `/api/results/result-${order}/media/`,
    prompt: `${slot} prompt`,
  };
  return order === 2
    ? [{ ...base, id: "generation-2-old", attempt: 1 }, { ...base, id: "generation-2", attempt: 2, version: 2 }]
    : [base];
});

const project = {
  id: "project-demo",
  name: "夏日家居上新",
  platform: "Shopee",
  market: "SG",
  template: "商品基础套图",
  size: "1:1",
  resolution: "1k",
  configurationStatus: "configured",
  defaultConfig: { platform: "shopee", market: "SG", sellerTier: "general", size: "1:1", resolution: "1k", globalPrompt: "" },
  status: "running",
  updatedAt: "2026-07-29T00:00:00Z",
  assets: [
    { id: "asset-lamp-main", name: "desk-lamp-main.png", kind: "image", imageUrl: "/api/assets/asset-lamp-main/media/" },
    { id: "asset-lamp-side", name: "desk-lamp-side.png", kind: "image", imageUrl: "/api/assets/asset-lamp-side/media/" },
  ],
  skus: [{
    id: "sku-lamp",
    name: "桌面护眼灯",
    sku: "LAMP-001",
    relationType: "single_product",
    version: 1,
    assetIds: ["asset-lamp-main"],
    assets: [{ id: "asset-lamp-main", name: "desk-lamp-main.png", kind: "image", imageUrl: "/api/assets/asset-lamp-main/media/" }],
    facts: "可调节灯臂",
    identityLock: "深蓝色灯头",
    brief: "极简书桌场景",
    preparationStatus: "ready",
    prompts: slotNames.map((slot, index) => ({ slotOrder: index + 1, slot, text: `${slot} prompt` })),
    outputs,
  }],
};

function response(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function renderApp(path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function dragRevisionArea({ left = 100, top = 100, right = 250, bottom = 250 } = {}) {
  const target = screen.getByLabelText("在结果图上拖拽框选修改区域") as HTMLElement;
  const bounds = {
    left: 0,
    top: 0,
    width: 500,
    height: 500,
    right: 500,
    bottom: 500,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
  target.getBoundingClientRect = () => bounds;
  const image = target.querySelector("img") as HTMLImageElement | null;
  if (image) {
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 500 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 500 });
  }
  fireEvent.mouseDown(target, { clientX: left, clientY: top });
  fireEvent.mouseMove(target, { clientX: right, clientY: bottom });
  fireEvent.mouseUp(target, { clientX: right, clientY: bottom });
}

async function openImportPanel() {
  await screen.findByRole("region", { name: "添加商品面板" });
}

function stubFetch(handler?: (url: string, init?: RequestInit) => Promise<unknown>) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (handler) return handler(url, init);
    if (url.includes("/csrf/")) return Promise.resolve(response(200, { csrf_token: "csrf-for-test" }));
    if (url.includes("/current-user/")) return Promise.resolve(response(200, { role: "operator" }));
    if (url.includes("/workspace/")) return Promise.resolve(response(200, { projects: [project] }));
    return Promise.resolve(response(200, project));
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

test("shows the operator dashboard without the old review center", async () => {
  renderApp();

  expect(await screen.findByRole("heading", { name: "工作台" })).toBeInTheDocument();
  expect(screen.getByText("夏日家居上新")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新建出图项目" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "审核中心" })).not.toBeInTheDocument();
});

test("redirects to login only after logout succeeds", async () => {
  const assign = vi.fn();
  vi.stubGlobal("location", { assign, origin: "http://localhost:3000" });
  stubFetch(async (url) => {
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf-for-test" });
    if (url === "/logout/") return { ok: true, status: 200, redirected: true, url: "http://localhost:3000/login/" };
    if (url.includes("/workspace/")) return response(200, { projects: [project] });
    return response(200, project);
  });
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

  await waitFor(() => expect(assign).toHaveBeenCalledWith("/login/"));
});

test("redirects to login when the logout session is already expired", async () => {
  const assign = vi.fn();
  vi.stubGlobal("location", { assign, origin: "http://localhost:3000" });
  stubFetch(async (url) => {
    if (url.includes("/csrf/")) {
      return { ok: true, status: 200, redirected: true, url: "http://localhost:3000/login/", json: async () => ({}) };
    }
    if (url.includes("/workspace/")) return response(200, { projects: [project] });
    return response(200, project);
  });
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

  await waitFor(() => expect(assign).toHaveBeenCalledWith("/login/"));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("shows a logout error and stays on the page when logout fails", async () => {
  const assign = vi.fn();
  vi.stubGlobal("location", { assign, origin: "http://localhost:3000" });
  stubFetch(async (url) => {
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf-for-test" });
    if (url === "/logout/") return response(500, { error: "logout unavailable" });
    if (url.includes("/workspace/")) return response(200, { projects: [project] });
    return response(200, project);
  });
  renderApp();

  fireEvent.click(await screen.findByRole("button", { name: "退出登录" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("退出登录失败，请重试。");
  expect(screen.getByRole("heading", { name: "工作台" })).toBeInTheDocument();
  expect(assign).not.toHaveBeenCalled();
});

test("opens a unified project workspace from the dashboard", async () => {
  renderApp("/projects/project-demo");

  expect(await screen.findByRole("heading", { name: "夏日家居上新" })).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "生产结果" })[0]).toHaveAttribute("href", "/projects/project-demo/results");
});

test("asks only for a project name before opening the project workbench", async () => {
  renderApp("/projects/new");

  expect(await screen.findByLabelText("项目名称")).toBeInTheDocument();
  expect(screen.queryByLabelText("平台")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("国家")).not.toBeInTheDocument();
});

test("keeps platform and country directly in the compact toolbar", async () => {
  renderApp("/projects/project-demo");

  expect(await screen.findByRole("button", { name: "Shopee 虾皮" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("项目国家")).toHaveValue("SG");
  expect(screen.queryByLabelText("项目店铺类型")).not.toBeInTheDocument();
});

test("keeps the add-product panel permanently visible", async () => {
  renderApp("/projects/project-demo");

  expect(await screen.findByRole("region", { name: "添加商品面板" })).toBeInTheDocument();
  expect(screen.getByLabelText("ERP SKU")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "选择图片/文件夹" })).toBeInTheDocument();
});

test("does not hide the add-product panel behind a dialog", async () => {
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.getByRole("region", { name: "添加商品面板" })).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "添加商品" })).not.toBeInTheDocument();
});

test("shows two explicit import choices for both upload and ERP SKU entry", async () => {
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  expect(screen.getByRole("menu", { name: "添加素材方式" })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "选择图片" })).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "选择文件夹" })).toBeInTheDocument();
  expect(screen.getByLabelText("选择图片")).toHaveAttribute("multiple");
  expect(screen.getByLabelText("选择图片")).not.toHaveAttribute("webkitdirectory");
  expect(screen.getByLabelText("选择文件夹")).toHaveAttribute("multiple");
  expect(screen.getByLabelText("选择文件夹")).toHaveAttribute("webkitdirectory");
  expect(screen.getByText("拖入图片或文件夹")).toBeInTheDocument();
  expect(screen.getByLabelText("ERP SKU")).toBeInTheDocument();
});

test("marks uploaded files for automatic mode without generating before Prompt preparation", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  const input = await screen.findByLabelText("选择图片");
  const file = new File(["image"], "front.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getAllByRole("button", { name: "导入并自动出图" })[0]);

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/assets/"))).toBe(true));
  const uploadCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/assets/"));
  expect((uploadCall?.[1]?.body as FormData).get("mode")).toBe("auto");
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/generate/"))).toBe(false);
});

test("posts uploaded files in organize mode without starting generation", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  fireEvent.change(await screen.findByLabelText("选择图片"), {
    target: { files: [new File(["image"], "front.png", { type: "image/png" })] },
  });
  fireEvent.click(screen.getAllByRole("button", { name: "导入后整理" })[0]);

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/assets/"))).toBe(true));
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/generate/"))).toBe(false);
});

test("previews pending images without filenames and does not resubmit successful files", async () => {
  const fetchMock = stubFetch(async (url) => {
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf-for-test" });
    if (url.includes("/assets/")) {
      return response(200, {
        asset_count: 1,
        imported: [{ filename: "front.png", asset_id: "new-asset", cluster_id: "new-cluster" }],
        rejected: [],
      });
    }
    return response(200, project);
  });
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  const input = await screen.findByLabelText("选择图片");
  fireEvent.change(input, {
    target: { files: [new File(["front"], "front.png", { type: "image/png" })] },
  });

  expect(screen.getByRole("img", { name: "待导入商品图 1" })).toBeInTheDocument();
  expect(screen.queryByText("front.png")).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "导入后整理" })[0]);
  await waitFor(() => expect(screen.queryByRole("img", { name: "待导入商品图 1" })).not.toBeInTheDocument());

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  fireEvent.change(await screen.findByLabelText("选择图片"), {
    target: { files: [new File(["side"], "side.png", { type: "image/png" })] },
  });
  fireEvent.click(screen.getAllByRole("button", { name: "导入后整理" })[0]);
  await waitFor(() => {
    const uploads = fetchMock.mock.calls.filter(([url]) => String(url).includes("/assets/"));
    expect(uploads).toHaveLength(2);
  });
  const uploads = fetchMock.mock.calls.filter(([url]) => String(url).includes("/assets/"));
  const firstFiles = (uploads[0]![1]!.body as FormData).getAll("files") as File[];
  const secondFiles = (uploads[1]![1]!.body as FormData).getAll("files") as File[];
  expect(firstFiles.map((file) => file.name)).toEqual(["front.png"]);
  expect(secondFiles.map((file) => file.name)).toEqual(["side.png"]);
});

test("lets users remove pending upload images before importing", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  fireEvent.change(await screen.findByLabelText("选择图片"), {
    target: { files: [
      new File(["front"], "front.png", { type: "image/png" }),
      new File(["side"], "side.png", { type: "image/png" }),
    ] },
  });

  fireEvent.click(screen.getByRole("button", { name: "移除待导入商品图 1" }));
  expect(screen.queryByRole("img", { name: "待导入商品图 2" })).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "导入后整理" })[0]);

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/assets/"))).toBe(true));
  const upload = fetchMock.mock.calls.find(([url]) => String(url).includes("/assets/"));
  const files = (upload?.[1]?.body as FormData).getAll("files") as File[];
  expect(files.map((file) => file.name)).toEqual(["side.png"]);
});

test("keeps pending files when the first upload request fails", async () => {
  stubFetch(async (url) => {
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf-for-test" });
    if (url.includes("/assets/")) return response(503, { error: "上传服务暂不可用" });
    return response(200, project);
  });
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.click(screen.getByRole("button", { name: "选择图片/文件夹" }));
  fireEvent.change(await screen.findByLabelText("选择图片"), {
    target: { files: [new File(["front"], "front.png", { type: "image/png" })] },
  });
  fireEvent.click(screen.getAllByRole("button", { name: "导入后整理" })[0]);

  expect(await screen.findByText("上传服务暂不可用")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "待导入商品图 1" })).toBeInTheDocument();
});

test("imports ERP SKUs in organize mode", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.change(await screen.findByLabelText("ERP SKU"), { target: { value: "LAMP-001\nLAMP-002" } });
  fireEvent.click(screen.getByRole("button", { name: "加载 SKU" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/sku-import/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/sku-import/"));
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ skus: ["LAMP-001", "LAMP-002"], mode: "organize" });
});

test("marks ERP imports for automatic mode without generating before Prompt preparation", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  await openImportPanel();
  fireEvent.change(await screen.findByLabelText("ERP SKU"), { target: { value: "LAMP-001" } });
  fireEvent.click(screen.getByRole("button", { name: "加载 SKU 并自动出图" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/sku-import/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/sku-import/"));
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ skus: ["LAMP-001"], mode: "auto" });
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/generate/"))).toBe(false);
});

test("renders product cards with inline identity and prompt editing", async () => {
  renderApp("/projects/project-demo");

  expect(await screen.findByRole("img", { name: "桌面护眼灯 商品参考图" })).toBeInTheDocument();
  expect(screen.getByLabelText("商品名称 桌面护眼灯")).toHaveValue("桌面护眼灯");
  fireEvent.click(screen.getByRole("button", { name: "桌面护眼灯 详情" }));
  expect(screen.queryByLabelText("多图关系")).not.toBeInTheDocument();
  expect(screen.getAllByLabelText("补充信息 桌面护眼灯").some((field) => (field as HTMLTextAreaElement).value.includes("深蓝色灯头"))).toBe(true);
  expect(screen.getByLabelText("01 标准白底产品图提示词")).toHaveValue("标准白底产品图 prompt");
});

test("saves the editable product brief through the cluster endpoint", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  const brief = await screen.findByLabelText("补充信息 桌面护眼灯");
  fireEvent.change(brief, { target: { value: "更明亮的书桌场景" } });
  fireEvent.blur(brief);

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/clusters/sku-lamp/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/clusters/sku-lamp/"));
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ product_facts: "更明亮的书桌场景" });
});

test("saves product platform and country overrides through the cluster endpoint", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  const platform = await screen.findByLabelText("商品平台 桌面护眼灯");
  fireEvent.change(platform, { target: { value: "tiktok" } });
  fireEvent.blur(platform);

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/clusters/sku-lamp/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/api/clusters/sku-lamp/"));
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ platform_override: "tiktok" });
});

test("uses in-app confirmation for product and asset deletion", async () => {
  const fetchMock = stubFetch();
  const nativeConfirm = vi.spyOn(window, "confirm").mockImplementation(() => {
    throw new Error("native confirm should not be used");
  });
  renderApp("/projects/project-demo");

  fireEvent.click(await screen.findByRole("button", { name: "桌面护眼灯 详情" }));
  fireEvent.click(screen.getByRole("button", { name: "删除商品参考图 1" }));
  const assetDialog = screen.getByRole("dialog", { name: "删除商品参考图" });
  fireEvent.click(within(assetDialog).getByRole("button", { name: "取消" }));
  expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("/api/assets/asset-lamp-main/") && init?.method === "DELETE")).toBe(false);

  fireEvent.click(screen.getByRole("button", { name: "删除商品" }));
  const productDialog = screen.getByRole("dialog", { name: "删除“桌面护眼灯”？" });
  fireEvent.click(within(productDialog).getByRole("button", { name: "删除商品" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("/api/clusters/sku-lamp/") && init?.method === "DELETE")).toBe(true));
  expect(nativeConfirm).not.toHaveBeenCalled();
});

test("starts generation for selected products and shows product and image counts", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo");

  const button = await screen.findByRole("button", { name: "正式生成（1）" });
  fireEvent.click(button);

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/generate/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/generate/"));
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ cluster_ids: ["sku-lamp"], slot_orders: [1, 2, 3, 4, 5, 6, 7, 8] });
});

test("allows the only product to be deselected", async () => {
  renderApp("/projects/project-demo");

  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 桌面护眼灯" }));

  expect(screen.getByRole("button", { name: "正式生成（0）" })).toBeDisabled();
});

test("keeps product details collapsed until requested", async () => {
  renderApp("/projects/project-demo");

  await screen.findByRole("checkbox", { name: "选择 桌面护眼灯" });
  expect(screen.queryByLabelText("商品身份")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "桌面护眼灯 详情" }));
  expect(screen.queryByLabelText("商品身份")).not.toBeInTheDocument();
  expect(screen.getAllByLabelText("补充信息 桌面护眼灯").some((field) => (field as HTMLTextAreaElement).value.includes("深蓝色灯头"))).toBe(true);
});

test("keeps an unidentified product name empty instead of inserting status text", async () => {
  const unnamed = {
    ...project,
    skus: [{ ...project.skus[0], name: "", sku: "" }],
  };
  stubFetch(async (url) => {
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf-for-test" });
    return response(200, unnamed);
  });
  renderApp("/projects/project-demo");

  const input = await screen.findByPlaceholderText("可不填，预备生成时识别");
  expect(input).toHaveValue("");
  expect(screen.queryByText("名称待确认")).not.toBeInTheDocument();
});

test("offers draggable thumbnails alongside the fixed product detail panel", async () => {
  renderApp("/projects/project-demo");

  fireEvent.click(await screen.findByRole("button", { name: "桌面护眼灯 详情" }));
  expect(screen.getByRole("button", { name: "查看并拖拽商品参考图 1" })).toHaveAttribute("aria-roledescription", "draggable");
  expect(screen.getByRole("dialog", { name: "桌面护眼灯 商品详情" })).toBeInTheDocument();
});

test("renders fifty editable product cards without expanding the workbench", async () => {
  const manyProducts = Array.from({ length: 50 }, (_, index) => ({
    ...project.skus[0],
    id: `sku-${index}`,
    name: `商品 ${index + 1}`,
    assetIds: ["asset-lamp-main"],
  }));
  const many = { ...project, skus: manyProducts };
  stubFetch(async (url) => {
    if (url.includes("/csrf/")) return response(200, { csrf_token: "csrf-for-test" });
    return response(200, many);
  });
  renderApp("/projects/project-demo");

  await screen.findByDisplayValue("商品 50");
  expect(screen.getAllByRole("textbox", { name: /^商品名称 商品/ })).toHaveLength(50);
  expect(document.querySelector(".product-card-grid")).toBeInTheDocument();
});

test("shows an eight-slot result grid for the project", async () => {
  renderApp("/projects/project-demo/results");

  expect(await screen.findByRole("heading", { name: "生产与结果" })).toBeInTheDocument();
  for (const slot of slotNames) expect(screen.getByText(slot)).toBeInTheDocument();
  expect(await screen.findByRole("img", { name: "标准白底产品图结果图" })).toHaveAttribute("loading", "lazy");
});

test("opens a lightbox when a result image is double-clicked and closes on Escape", async () => {
  renderApp("/projects/project-demo/results");

  fireEvent.doubleClick(await screen.findByRole("img", { name: "标准白底产品图结果图" }));

  const dialog = await screen.findByRole("dialog", { name: "标准白底产品图 放大查看" });
  expect(dialog).toHaveClass("fixed", "z-[70]");
  expect(screen.getByRole("img", { name: "标准白底产品图 放大图" })).toHaveAttribute("src", "/api/results/result-1/media/");

  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "标准白底产品图 放大查看" })).not.toBeInTheDocument();
});

test("selects the latest successful version by default for export", async () => {
  renderApp("/projects/project-demo/results");

  const latest = await screen.findByRole("checkbox", { name: "导出 核心卖点图 v2" });
  expect(latest).toBeChecked();
  expect(screen.getByText("历史版本")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "核心卖点图 v1 历史图" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看历史版本 核心卖点图 v1" }));
  expect(screen.getByRole("heading", { name: "核心卖点图 v1" })).toBeInTheDocument();
});

test("keeps the previous successful result exportable while a new version is queued", async () => {
  const queuedProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      outputs: [
        { ...outputs[0], id: "generation-1-v1", attempt: 1 },
        { ...outputs[0], id: "generation-1-v2", attempt: 2, status: "queued", reviewStatus: "pending", imageUrl: undefined },
        ...outputs.slice(1),
      ],
    }],
  };
  const fetchMock = stubFetch((url) => {
    if (url.includes("/csrf/")) return Promise.resolve(response(200, { csrf_token: "csrf-for-test" }));
    if (url.includes("/export/")) return Promise.resolve({ ok: true, status: 200, blob: async () => new Blob(["zip"]) });
    return Promise.resolve(response(200, url.includes("/workspace/") ? { projects: [queuedProject] } : queuedProject));
  });
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:zip"), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  renderApp("/projects/project-demo/results");

  expect(await screen.findByRole("button", { name: "下载选中 ZIP（8 张）" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载当前图片" })).toHaveAttribute("href", "/api/results/result-1/media/");
  fireEvent.click(screen.getByRole("button", { name: "下载选中 ZIP（8 张）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/export/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/export/"));
  expect(JSON.parse(String(call?.[1]?.body)).generation_ids).toContain("generation-1-v1");
  expect(JSON.parse(String(call?.[1]?.body)).generation_ids).not.toContain("generation-1-v2");
});

test("lets operators cancel one result from the ZIP selection", async () => {
  renderApp("/projects/project-demo/results");

  const first = await screen.findByRole("checkbox", { name: "导出 标准白底产品图 v1" });
  fireEvent.click(first);

  expect(first).not.toBeChecked();
  expect(screen.getByRole("button", { name: "下载选中 ZIP（7 张）" })).toBeInTheDocument();
});

test("posts only selected generation IDs when downloading the ZIP", async () => {
  const fetchMock = stubFetch((url) => {
    if (url.includes("/csrf/")) return Promise.resolve(response(200, { csrf_token: "csrf-for-test" }));
    if (url.includes("/export/")) return Promise.resolve({ ok: true, status: 200, blob: async () => new Blob(["zip"]) });
    return Promise.resolve(response(200, url.includes("/workspace/") ? { projects: [project] } : project));
  });
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:zip"), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  renderApp("/projects/project-demo/results");

  fireEvent.click(await screen.findByRole("checkbox", { name: "导出 标准白底产品图 v1" }));
  fireEvent.click(screen.getByRole("button", { name: "下载选中 ZIP（7 张）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/export/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/export/"));
  expect(JSON.parse(String(call?.[1]?.body)).generation_ids).not.toContain("generation-1");
});

test("offers single-image downloads and bulk ZIP selection controls", async () => {
  renderApp("/projects/project-demo/results");

  const single = await screen.findByRole("link", { name: "下载 标准白底产品图 v1" });
  expect(single).toHaveAttribute("href", "/api/results/result-1/media/");
  expect(single.getAttribute("download")).toContain("标准白底产品图");

  const first = screen.getByRole("checkbox", { name: "导出 标准白底产品图 v1" });
  fireEvent.click(first);
  expect(first).not.toBeChecked();

  fireEvent.click(screen.getByRole("button", { name: "勾选全部" }));
  expect(first).toBeChecked();
  expect(screen.getByRole("button", { name: "下载选中 ZIP（8 张）" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "取消勾选" }));
  expect(first).not.toBeChecked();
  expect(screen.getByRole("button", { name: "下载选中 ZIP（0 张）" })).toBeDisabled();
});

test("exports completed results by default without approval and shows the generation prompt", async () => {
  const pendingProject = {
    ...project,
    skus: [{ ...project.skus[0], outputs: outputs.map((output) => ({ ...output, reviewStatus: "pending" })) }],
  };
  const fetchMock = stubFetch((url) => {
    if (url.includes("/csrf/")) return Promise.resolve(response(200, { csrf_token: "csrf-for-test" }));
    return Promise.resolve(response(200, url.includes("/workspace/") ? { projects: [pendingProject] } : pendingProject));
  });
  renderApp("/projects/project-demo/results");

  expect(await screen.findByRole("checkbox", { name: "导出 标准白底产品图 v1" })).toBeChecked();
  expect(screen.getByRole("button", { name: "下载选中 ZIP（8 张）" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "通过此图，允许导出" })).not.toBeInTheDocument();
  expect(screen.queryByText("没有审核通过的图片，先在下方通过需要导出的图。")).not.toBeInTheDocument();
  expect(screen.getByText("生成提示词")).toBeInTheDocument();
  expect(screen.getByDisplayValue("Standard white-background product hero prompt")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "下载选中 ZIP（8 张）" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/export/"))).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/export/"));
  expect(JSON.parse(String(call?.[1]?.body)).generation_ids).toContain("generation-1");
});

test("requests a new version for a successful result", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo/results");

  fireEvent.click(await screen.findByRole("button", { name: "再生成 标准白底产品图" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/generations/generation-1/regenerate/",
    expect.objectContaining({ method: "POST" }),
  ));
});

test("does not submit duplicate result regeneration while the request is pending", async () => {
  let finishRegenerate: (() => void) | undefined;
  const fetchMock = stubFetch((url) => {
    if (url.includes("/csrf/")) return Promise.resolve(response(200, { csrf_token: "csrf-for-test" }));
    if (url.includes("/workspace/")) return Promise.resolve(response(200, { projects: [project] }));
    if (url === "/api/generations/generation-1/regenerate/") {
      return new Promise((resolve) => {
        finishRegenerate = () => resolve(response(200, { id: "generation-new", attempt: 2, status: "queued" }));
      });
    }
    return Promise.resolve(response(200, project));
  });
  renderApp("/projects/project-demo/results");

  const button = await screen.findByRole("button", { name: "再生成 标准白底产品图" });
  fireEvent.click(button);
  await waitFor(() => expect(button).toBeDisabled());
  fireEvent.click(button);

  expect(fetchMock.mock.calls.filter(([url]) => String(url) === "/api/generations/generation-1/regenerate/")).toHaveLength(1);
  finishRegenerate?.();
});

test("pauses one active result from the result page", async () => {
  const activeProject = {
    ...project,
    skus: [{
      ...project.skus[0],
      outputs: [{ ...outputs[0], id: "generation-running", status: "running", reviewStatus: "pending", imageUrl: undefined }],
    }],
  };
  const fetchMock = stubFetch((url) => {
    if (url.includes("/csrf/")) return Promise.resolve(response(200, { csrf_token: "csrf-for-test" }));
    return Promise.resolve(response(200, url.includes("/workspace/") ? { projects: [activeProject] } : activeProject));
  });
  renderApp("/projects/project-demo/results");

  fireEvent.click(await screen.findByRole("button", { name: "暂停 标准白底产品图" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-demo/pause/",
    expect.objectContaining({ method: "POST" }),
  ));
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/projects/project-demo/pause/");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ generation_ids: ["generation-running"] });
});

test("opens a large revision editor and lets users undo or clear mistaken marks", async () => {
  renderApp("/projects/project-demo/results");

  fireEvent.click(await screen.findByRole("button", { name: "修改 标准白底产品图 v1" }));

  expect(await screen.findByRole("dialog", { name: "修改 标准白底产品图 v1" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "添加修改区域" }));
  expect(screen.queryByText("标记 1")).not.toBeInTheDocument();
  dragRevisionArea();
  fireEvent.change(screen.getByLabelText("标记 1 修改说明"), { target: { value: "把这里的文字放大" } });
  dragRevisionArea({ left: 240, top: 240, right: 420, bottom: 420 });
  expect(screen.getByText("标记 2")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "撤销上一步" }));
  expect(screen.queryByText("标记 2")).not.toBeInTheDocument();

  dragRevisionArea({ left: 260, top: 260, right: 440, bottom: 440 });
  fireEvent.click(screen.getByRole("button", { name: "删除标记 1" }));
  expect(screen.queryByText("标记 2")).not.toBeInTheDocument();
  expect(screen.getByText("标记 1")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "清除全部" }));
  expect(screen.queryByText("标记 1")).not.toBeInTheDocument();
});

test("submits result revision annotations to create a new image version", async () => {
  const fetchMock = stubFetch();
  renderApp("/projects/project-demo/results");

  fireEvent.click(await screen.findByRole("button", { name: "修改 标准白底产品图 v1" }));
  fireEvent.click(await screen.findByRole("button", { name: "添加修改区域" }));
  dragRevisionArea();
  fireEvent.change(screen.getByLabelText("整体修改说明"), { target: { value: "整体文字放大，商品不变" } });
  fireEvent.change(screen.getByLabelText("标记 1 修改说明"), { target: { value: "把这里的泰文改清晰" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Logo / 文字" }));
  fireEvent.click(screen.getByRole("button", { name: "提交修改生成新版本" }));

  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/generations/generation-1/revise/")).toBe(true));
  const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/generations/generation-1/revise/");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    issue_tags: ["logo_text"],
    description: "整体文字放大，商品不变",
    annotations: [{
      kind: "rect",
      rect: [0.2, 0.2, 0.3, 0.3],
      color: "#e11d48",
      width: 2,
      note: "把这里的泰文改清晰",
    }],
  });
});

test("routes production links to the project result page", async () => {
  renderApp("/production");

  expect(await screen.findByRole("heading", { name: "生产队列" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看结果" })).toHaveAttribute("href", "/projects/project-demo/results");
});

test("shows an actionable error rather than mock content when workspace access is denied", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(403, { error: "forbidden" })));
  renderApp("/");

  expect(await screen.findByRole("alert")).toHaveTextContent("没有权限访问");
});

test("offers a login link when Django redirects an expired session to HTML", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    redirected: true,
    headers: new Headers({ "content-type": "text/html" }),
    json: async () => "<html>login</html>",
  }));
  renderApp("/");

  expect(await screen.findByRole("alert")).toHaveTextContent("登录已失效或需修改密码");
  expect(screen.getByRole("link", { name: "重新登录" })).toHaveAttribute("href", "/login/");
});
