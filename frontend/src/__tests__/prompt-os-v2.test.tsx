import { afterEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { updateCluster } from "../api";
import { PromptEditor } from "../components/PromptEditor";
import type { ProductSku } from "../types";

const sku: ProductSku = {
  id: "cluster-1",
  name: "便携榨汁杯",
  sku: "CUP-001",
  relationType: "single_product",
  version: 3,
  assetIds: [],
  facts: "透明杯身",
  identityLock: "保留绿色杯盖与双叶刀头",
  brief: "明亮厨房场景",
  prompts: [{ slotOrder: 1, slot: "白底标准图", text: "原始白底 Prompt" }],
  outputs: [],
  analysisSnapshot: {
    fact_ledger: {
      facts: [
        {
          fact_id: "fact.color",
          statement: "杯盖为绿色",
          fact_class: "confirmed",
          confidence: 1,
          evidence_refs: ["erp:CUP-001"],
          risk_level: "low",
          allowed_uses: ["identity", "visual_prompt"],
          review_note: "",
        },
        {
          fact_id: "fact.material",
          statement: "杯身可能为食品级塑料",
          fact_class: "inferred",
          confidence: 0.68,
          evidence_refs: ["asset:front"],
          risk_level: "high",
          allowed_uses: ["scene_planning"],
          review_note: "材质需人工确认",
        },
      ],
      review_summary: {
        confirmed_count: 1,
        observed_count: 0,
        inferred_count: 1,
        high_risk_count: 1,
      },
      blocked_claim_topics: ["certification", "medical_efficacy", "price"],
    },
    rule_gate: {
      decision: "block",
      hard_blocks: ["高风险材质推断不得进入消费者文案"],
      semantic_risks: ["“食品级”缺少确认来源"],
      warnings: ["发布前需人工复核材质"],
    },
  },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows Chinese product recognition details without exposing soft compliance noise", () => {
  render(<PromptEditor sku={sku} onSave={() => undefined} />);

  expect(screen.getByText("商品识别信息")).toBeInTheDocument();
  expect(screen.getAllByText("杯盖为绿色").length).toBeGreaterThan(0);
  expect(screen.getAllByText("杯身可能为食品级塑料").length).toBeGreaterThan(0);
  expect(screen.getByText("已确认 · 100%")).toBeInTheDocument();
  expect(screen.getByText("辅助判断 · 68%")).toBeInTheDocument();
  expect(screen.getByText("确认 1 · 图片观察 0 · 辅助判断 1")).toBeInTheDocument();
  expect(screen.queryByText(/这些内容不能靠 AI 猜出来写进图片/)).not.toBeInTheDocument();
  expect(screen.queryByText(/certification|medical_efficacy|price/)).not.toBeInTheDocument();
  expect(screen.queryByText("规则 / 合规阻断")).not.toBeInTheDocument();
  expect(screen.queryByText(/高风险材质推断不得进入消费者文案/)).not.toBeInTheDocument();
  expect(screen.queryByText(/“食品级”缺少确认来源/)).not.toBeInTheDocument();
  expect(screen.queryByText(/发布前需人工复核材质/)).not.toBeInTheDocument();
});

test("renders long mixed-language recognition facts as compact Chinese operator text", () => {
  render(<PromptEditor sku={{
    ...sku,
    analysisSnapshot: {
      fact_ledger: {
        facts: [
          "Yellow plush toy",
          "large round head",
          "two big round eyes",
          "short arms",
          "short legs",
          "plush texture",
          "confirmed_points",
        ].map((statement, index) => ({
          fact_id: `fact-${index}`,
          statement,
          fact_class: "confirmed" as const,
          confidence: 1,
          evidence_refs: ["confirmed_points"],
          risk_level: "low",
          allowed_uses: ["visual_prompt"],
          review_note: "",
        })),
        review_summary: { confirmed_count: 7, observed_count: 0, inferred_count: 0, high_risk_count: 0 },
      },
    },
  }} onSave={() => undefined} />);

  expect(screen.getAllByText("黄色毛绒玩偶").length).toBeGreaterThan(0);
  expect(screen.getAllByText("圆形头部").length).toBeGreaterThan(0);
  expect(screen.getAllByText("两只大圆眼睛").length).toBeGreaterThan(0);
  expect(screen.getByText("查看全部识别证据（6）")).toBeInTheDocument();
  expect(screen.queryByText("large round head")).not.toBeInTheDocument();
  expect(screen.queryByText("confirmed_points")).not.toBeInTheDocument();
});

test("shows only the final editable visual prompt without localized-copy side panels", () => {
  render(<PromptEditor sku={{
    ...sku,
    prompts: [
      {
        slotOrder: 2,
        slot: "核心卖点图",
        text: "Create a bright kitchen scene. Show quoted visible text exactly: \"Xay mịn mỗi sáng\" and \"Mang đi là xay\".",
      },
    ],
  }} onSave={() => undefined} />);

  const field = screen.getByLabelText("02 核心卖点图提示词") as HTMLTextAreaElement;
  expect(field.value).toContain("Create a bright kitchen scene");
  expect(field.value).toContain("Xay mịn mỗi sáng");
  expect(screen.queryByText(/每天早上顺滑搅拌/)).not.toBeInTheDocument();
  expect(screen.queryByText(/图片文案/)).not.toBeInTheDocument();
  expect(screen.queryByText(/回译/)).not.toBeInTheDocument();
  expect(screen.queryByText("场景代入")).not.toBeInTheDocument();
  expect(screen.queryByText(/购买任务：/)).not.toBeInTheDocument();
  expect(screen.queryByText("高级：最终生图指令")).not.toBeInTheDocument();
  expect(screen.queryByText(/localized_copy|creative_strategy|back_translation/)).not.toBeInTheDocument();
});

test("shows the backend final English image prompt without inventing a field summary", () => {
  const finalPrompt = "Create a polished 1:1 ecommerce listing image for Shopee. The product fills the frame in a close-up micro-tilt angle with soft side light bringing out the material texture. Show this exact visible text: \"พร้อมใช้ทุกวัน\".";
  render(<PromptEditor sku={{
    ...sku,
    prompts: [{
      slotOrder: 3,
      slot: "Product detail",
      text: finalPrompt,
    }],
  }} onSave={() => undefined} />);

  const field = screen.getByLabelText("03 细节特写图提示词") as HTMLTextAreaElement;
  expect(field.value).toBe(finalPrompt);
  expect(field.value).not.toContain("主体：");
  expect(field.value).not.toContain("动作：");
  expect(field.value).not.toContain("构图：");
  expect(field.value).toContain("พร้อมใช้ทุกวัน");
  expect(screen.queryByText(/回译/)).not.toBeInTheDocument();
});

test("shows the available model prompt when Chinese display prompt is missing", () => {
  render(<PromptEditor sku={{
    ...sku,
    preparationStatus: "ready",
    prompts: [{
      slotOrder: 4,
      slot: "Function",
      text: "Create a polished ecommerce listing image. Scene: a real use scene selected from buyer motivation.",
      localizedCopy: { language: "en", lines: ["Useful right when it matters"] },
    }],
  }} onSave={() => undefined} />);

  const field = screen.getByLabelText("04 功能说明图提示词") as HTMLTextAreaElement;
  expect(field.value).toContain("Create a polished ecommerce listing image");
  expect(field.placeholder).not.toContain("此槽位提示词缺失");
  expect(field.closest("label")).not.toHaveTextContent("此槽位提示词缺失，请重新预备生成");
});

test("uses placeholders instead of editable fake prompt text before preparation", () => {
  render(<PromptEditor sku={{ ...sku, prompts: [] }} onSave={() => undefined} />);

  const field = screen.getByLabelText("02 核心卖点图提示词") as HTMLTextAreaElement;
  expect(field.value).toBe("");
  expect(field.placeholder).toContain("预备生成后显示");
  expect(screen.getByText("9 张生成提示词")).toBeInTheDocument();
  expect(screen.getByLabelText("09 品质信任图提示词")).toHaveValue("");
});

test("autosaves edited prompts as a structured snake-case array", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ csrf_token: "csrf" }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ id: "cluster-1", version: 4 }) });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <PromptEditor
      sku={sku}
      onSave={(payload) => {
        return updateCluster(sku.id, sku.version, payload);
      }}
    />,
  );

  const field = screen.getByLabelText("01 白底标准图提示词");
  expect(screen.queryByRole("button", { name: "保存提示词" })).not.toBeInTheDocument();
  fireEvent.change(field, {
    target: { value: "纯白背景，保留绿色杯盖" },
  });
  fireEvent.blur(field);

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toMatchObject({
    expected_version: 3,
    prompts: [{ slot_order: 1, prompt: "纯白背景，保留绿色杯盖" }],
  });
});

test("shows editable Chinese planning plus readonly English final and saves display_prompt for bilingual prompts", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ csrf_token: "csrf" }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ id: "cluster-1", version: 4 }) });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <PromptEditor
      sku={{
        ...sku,
        prompts: [{
          slotOrder: 1,
          slot: "白底标准图",
          text: "Create a clean white-background hero. Show this exact text: \"พร้อมใช้ทุกวัน\".",
          displayPrompt: "纯白背景，突出完整商品，干净易上架",
        }],
      }}
      onSave={(payload) => updateCluster(sku.id, sku.version, payload)}
    />,
  );

  const zh = screen.getByLabelText("01 白底标准图提示词中文策划") as HTMLTextAreaElement;
  expect(zh.value).toBe("纯白背景，突出完整商品，干净易上架");
  const en = screen.getByLabelText("01 白底标准图提示词出图用英文") as HTMLTextAreaElement;
  expect(en.value).toBe("Create a clean white-background hero. Show this exact text: \"พร้อมใช้ทุกวัน\".");
  expect(en.readOnly).toBe(true);
  expect(screen.getByText("01 白底标准图提示词 · 中文策划")).toBeInTheDocument();
  expect(screen.getByText("出图用英文（生成时按中文重新翻译）")).toBeInTheDocument();

  fireEvent.change(zh, { target: { value: "新中文策划：强调一体式机身" } });
  fireEvent.blur(zh);

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toMatchObject({
    expected_version: 3,
    prompts: [{ slot_order: 1, display_prompt: "新中文策划：强调一体式机身" }],
  });
});

test("keeps dirty identity and prompt drafts across a polling snapshot", () => {
  const view = render(<PromptEditor sku={sku} onSave={() => undefined} />);

  fireEvent.change(screen.getByLabelText("01 白底标准图提示词"), { target: { value: "保留本地白底 Prompt" } });

  view.rerender(<PromptEditor sku={{
    ...sku,
    relationType: "variant_group",
    identityLock: "服务器身份锁",
    brief: "服务器 Brief",
    prompts: [{ slotOrder: 1, slot: "白底标准图", text: "服务器 Prompt" }],
  }} onSave={() => undefined} />);

  expect(screen.getByLabelText("01 白底标准图提示词")).toHaveValue("保留本地白底 Prompt");
});

test("keeps a successful prompt save while the parent still renders the old SKU snapshot", async () => {
  const onSave = vi.fn().mockResolvedValue({ id: "cluster-1", version: 4 });
  const view = render(<PromptEditor sku={sku} onSave={onSave} />);

  const field = screen.getByLabelText("01 白底标准图提示词");
  fireEvent.change(field, { target: { value: "已保存白底提示词" } });
  fireEvent.blur(field);
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  view.rerender(<PromptEditor sku={sku} onSave={onSave} />);

  expect(screen.getByLabelText("01 白底标准图提示词")).toHaveValue("已保存白底提示词");
});

test("adopts the acknowledged SKU snapshot as the new prompt baseline", async () => {
  const onSave = vi.fn().mockResolvedValue({ id: "cluster-1", version: 4 });
  const view = render(<PromptEditor sku={sku} onSave={onSave} />);

  const field = screen.getByLabelText("01 白底标准图提示词");
  fireEvent.change(field, { target: { value: "已保存白底提示词" } });
  fireEvent.blur(field);
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));

  view.rerender(<PromptEditor sku={{ ...sku, version: 4, prompts: [{ slotOrder: 1, slot: "白底标准图", text: "服务器确认提示词" }] }} onSave={onSave} />);
  expect(screen.getByLabelText("01 白底标准图提示词")).toHaveValue("服务器确认提示词");

  view.rerender(<PromptEditor sku={{ ...sku, version: 5, prompts: [{ slotOrder: 1, slot: "白底标准图", text: "后续远端提示词" }] }} onSave={onSave} />);
  expect(screen.getByLabelText("01 白底标准图提示词")).toHaveValue("后续远端提示词");
});
