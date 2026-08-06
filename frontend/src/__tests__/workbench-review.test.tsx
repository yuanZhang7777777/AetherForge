import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError } from "../api";
import { collectDroppedFiles, ImportPanel } from "../components/ImportPanel";
import { ProductCard } from "../components/ProductCard";
import type { ProductSku } from "../types";

const sku: ProductSku = {
  id: "sku-1", name: "旧名称", sku: "SKU-1", relationType: "single_product", assetIds: ["asset-1"],
  assets: [{ id: "asset-1", name: "hidden.png", kind: "image", imageUrl: "/image" }],
  facts: "旧补充信息", productFacts: "旧补充信息", productStyle: "旧风格", identityLock: "", brief: "旧风格", version: 1, preparationStatus: "blocked",
  preparation: { status: "blocked", stage: "N2", current: 2, total: 7, error: "请确认商品身份" },
  overrides: { platform: null, market: null, sellerTier: null },
  effectiveConfig: { platform: "shopee", market: "SG", sellerTier: "general", size: "1:1", resolution: "1k", globalPrompt: "" },
  analysisSnapshot: { readiness: { status: "blocked", code: "identity_needs_input" } },
  prompts: [{ slotOrder: 1, slot: "hero", text: "白底图 Prompt" }],
  outputs: [],
};

const props = {
  assets: sku.assets!, mergeableAssets: [], selected: true, onSelect: () => undefined, onMerge: () => undefined,
  onReload: vi.fn(), onDeleteAsset: () => undefined, onDelete: () => undefined,
};

afterEach(cleanup);

test("combines dirty card fields into one explicit versioned save", async () => {
  const onSave = vi.fn().mockResolvedValue({ id: "sku-1", version: 2 });
  render(<ProductCard {...props} sku={sku} onSave={onSave} />);

  fireEvent.change(screen.getByLabelText("商品名称 旧名称"), { target: { value: "新名称" } });
  fireEvent.change(screen.getByLabelText("商品平台 新名称"), { target: { value: "tiktok" } });
  fireEvent.change(screen.getByLabelText("商品国家 新名称"), { target: { value: "VN" } });
  fireEvent.change(screen.getByLabelText("补充信息 新名称"), { target: { value: "展示使用方式\n风格/要求：自然光" } });
  fireEvent.blur(screen.getByLabelText("补充信息 新名称"));

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(onSave).toHaveBeenCalledWith({ name: "新名称", product_facts: "展示使用方式\n风格/要求：自然光", platform_override: "tiktok", market_override: "VN" }, 1);
});

test("preserves a dirty card draft and retries with the refreshed version after a 409", async () => {
  const onSave = vi.fn().mockRejectedValueOnce(new ApiError(409, "版本已更新"));
  const onReload = vi.fn().mockResolvedValue(undefined);
  const view = render(<ProductCard {...props} sku={sku} onSave={onSave} onReload={onReload} />);

  fireEvent.change(screen.getByLabelText("商品名称 旧名称"), { target: { value: "仍要保留的名称" } });
  fireEvent.blur(screen.getByLabelText("商品名称 仍要保留的名称"));
  expect(await screen.findByText("商品信息已更新，请保留修改后重试")).toBeInTheDocument();
  expect(onReload).toHaveBeenCalledTimes(1);

  view.rerender(<ProductCard {...props} sku={{ ...sku, version: 2 }} onSave={onSave.mockResolvedValueOnce({ id: "sku-1", version: 3 })} onReload={onReload} />);
  expect(screen.getByLabelText("商品名称 仍要保留的名称")).toHaveValue("仍要保留的名称");
  fireEvent.blur(screen.getByLabelText("商品名称 仍要保留的名称"));
  await waitFor(() => expect(onSave).toHaveBeenLastCalledWith({ name: "仍要保留的名称" }, 2));
});

test("keeps typed ERP SKUs and failed error notes after a partial import", async () => {
  render(<ImportPanel onUpload={vi.fn()} onImported={vi.fn()} onSkuImport={vi.fn().mockResolvedValue({
    imported: 1, failed: 1, items: [
      { sku: "OK-1", status: "imported", errorCode: null },
      { sku: "MISSING", status: "failed", errorCode: "sku_not_found" },
    ],
  })} />);

  fireEvent.change(screen.getByLabelText("ERP SKU"), { target: { value: "OK-1\nMISSING" } });
  fireEvent.click(screen.getByRole("button", { name: "加载 SKU" }));

  expect(await screen.findByText("MISSING：SKU 不存在或无可用商品图片")).toBeInTheDocument();
  expect(screen.getByLabelText("ERP SKU")).toHaveValue("OK-1\nMISSING");
});

test("accepts multiple dropped images when the browser has no folder entries", async () => {
  const first = new File(["one"], "one.png", { type: "image/png" });
  const second = new File(["two"], "two.png", { type: "image/png" });
  const files = await collectDroppedFiles({ items: [], files: [first, second] } as unknown as DataTransfer);
  expect(files.map((file) => file.name)).toEqual(["one.png", "two.png"]);
});

test("shows exact blocked progress and no raw implementation configuration", () => {
  render(<ProductCard {...props} sku={sku} onSave={vi.fn()} />);
  expect(screen.getByText("需要补充信息 · 请确认商品身份")).toBeInTheDocument();
  expect(screen.getByLabelText("商品平台 旧名称")).toHaveDisplayValue("跟随项目");
  expect(screen.getByLabelText("商品国家 旧名称")).toHaveDisplayValue("跟随项目");
});

test("keeps AI recognized identity facts visible in the product card", () => {
  const recognizedSku: ProductSku = {
    ...sku,
    name: "rice cooker",
    productNameSource: "ai",
    facts: "rice cooker, white body, black top rim",
    productFacts: "rice cooker, white body, black top rim",
    identityLock: "rice cooker with white body and black top rim",
  };
  render(<ProductCard {...props} sku={recognizedSku} onSave={vi.fn()} />);

  const card = screen.getByRole("group", { name: /电饭锅 商品卡片/ });
  const supplement = within(card).getByLabelText("补充信息 电饭锅") as HTMLTextAreaElement;
  expect(supplement.value).toContain("电饭锅");
  expect(supplement.value).toContain("white body");
  expect(supplement.value).toContain("black top rim");
  expect(supplement.value).toContain("身份保持：");
});

test("keeps the large product card editable without forcing a square", () => {
  const view = render(<ProductCard {...props} sku={sku} onSave={vi.fn()} />);
  expect(view.container.querySelector(".product-card")).not.toHaveClass("aspect-square");
  expect(screen.getByRole("img", { name: "旧名称 商品参考图" })).toHaveClass("object-contain");
  expect(screen.getByLabelText("商品平台 旧名称")).toBeInTheDocument();
  expect(screen.getByLabelText("补充信息 旧名称")).toBeInTheDocument();
});

test("shows multiple references for drag sorting without a relation selector", () => {
  const onSave = vi.fn().mockResolvedValue({ id: "sku-1", version: 2 });
  const groupedSku = {
    ...sku,
    relationType: "same_product" as const,
    assetIds: ["asset-1", "asset-2"],
    assets: [
      ...sku.assets!,
      { id: "asset-2", name: "second.png", kind: "image" as const, imageUrl: "/image-2" },
    ],
  };
  render(<ProductCard {...props} sku={groupedSku} assets={groupedSku.assets} onSave={onSave} />);

  expect(screen.queryByLabelText("参考图关系 旧名称")).not.toBeInTheDocument();
  expect(screen.getByRole("list", { name: "旧名称 参考图排序" })).toHaveTextContent("主");
  expect(screen.getByRole("button", { name: "查看并拖拽商品参考图 1" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看并拖拽商品参考图 2" })).toBeInTheDocument();
  expect(onSave).not.toHaveBeenCalled();
});

test("clicking a thumbnail changes the large preview without changing primary order", () => {
  const groupedSku = {
    ...sku,
    assetIds: ["asset-1", "asset-2"],
    assets: [
      ...sku.assets!,
      { id: "asset-2", name: "second.png", kind: "image" as const, imageUrl: "/image-2" },
    ],
  };
  render(<ProductCard {...props} sku={groupedSku} assets={groupedSku.assets} onSave={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: "查看并拖拽商品参考图 2" }));

  expect(screen.getByRole("img", { name: "旧名称 商品参考图" })).toHaveAttribute("src", "/image-2");
  expect(screen.getByRole("list", { name: "旧名称 参考图排序" })).toHaveTextContent("主");
});

test("only the thumbnail strip starts asset drag interactions", () => {
  const groupedSku = {
    ...sku,
    assetIds: ["asset-1", "asset-2"],
    assets: [
      ...sku.assets!,
      { id: "asset-2", name: "second.png", kind: "image" as const, imageUrl: "/image-2" },
    ],
  };
  const view = render(<ProductCard {...props} sku={groupedSku} assets={groupedSku.assets} onSave={vi.fn()} />);

  expect(screen.getByRole("button", { name: "查看并拖拽商品参考图 1" })).toHaveAttribute("data-dnd-activator");
  expect(view.container.querySelector('[aria-label="旧名称 商品主预览"]')).not.toHaveAttribute("data-dnd-activator");
});

test("renders product details in a fixed side panel", () => {
  render(<ProductCard {...props} sku={sku} expanded onSave={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "旧名称 商品详情" })).toHaveClass("fixed", "overscroll-contain");
  expect(screen.queryByLabelText("商品身份")).not.toBeInTheDocument();
});

test("uses taller product platform and country selectors", () => {
  render(<ProductCard {...props} sku={sku} onSave={vi.fn()} />);

  expect(screen.getByLabelText("商品平台 旧名称")).toHaveClass("h-12", "min-h-12");
  expect(screen.getByLabelText("商品国家 旧名称")).toHaveClass("h-12", "min-h-12");
});
