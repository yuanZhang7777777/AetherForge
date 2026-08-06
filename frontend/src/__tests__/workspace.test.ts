import { expect, test } from "vitest";
import { currentOutputs, mergeProjectProgress, projectHasActiveWork, progressPollInterval, workspacePollInterval } from "../workspace";
import type { Project } from "../types";

test("counts only the highest attempt for each output slot while retaining version history", () => {
  const result = currentOutputs([
    { id: "old-main", slot: "主图", slotId: "main", slotOrder: 1, attempt: 1 },
    { id: "new-main", slot: "主图", slotId: "main", slotOrder: 1, attempt: 2 },
    { id: "detail", slot: "细节图", slotId: "detail", slotOrder: 2, attempt: 1 },
  ]);

  expect(result.map((output) => output.id)).toEqual(["new-main", "detail"]);
});

test("keeps different slots with the same display name and orders them by server slot order", () => {
  const result = currentOutputs([
    { id: "wide-v1", slot: "详情图", slotId: "wide", slotOrder: 20, attempt: 1 },
    { id: "close-v1", slot: "详情图", slotId: "close", slotOrder: 10, attempt: 1 },
    { id: "wide-v2", slot: "详情图", slotId: "wide", slotOrder: 20, attempt: 2 },
  ]);

  expect(result.map((output) => output.id)).toEqual(["close-v1", "wide-v2"]);
});

test("polls lightweight progress frequently and full workspace snapshots slowly", () => {
  expect(progressPollInterval(true, false)).toBe(3000);
  expect(progressPollInterval(true, true)).toBe(15000);
  expect(progressPollInterval(false, false)).toBe(false);
  expect(workspacePollInterval(true, false)).toBe(15000);
  expect(workspacePollInterval(true, true)).toBe(60000);
  expect(workspacePollInterval(false, false)).toBe(false);
});

test("polls only real active project, product, or output states", () => {
  expect(projectHasActiveWork({ status: "queued", skus: [{ preparationStatus: "ready", outputs: [] }] })).toBe(true);
  expect(projectHasActiveWork({ status: "running", skus: [{ preparationStatus: "ready", outputs: [] }] })).toBe(true);
  expect(projectHasActiveWork({ status: "draft", skus: [{ preparationStatus: "pending", outputs: [] }] })).toBe(true);
  expect(projectHasActiveWork({ status: "draft", skus: [{ preparationStatus: "preparing", outputs: [] }] })).toBe(true);
  expect(projectHasActiveWork({ status: "draft", skus: [{ preparationStatus: "ready", outputs: [] }] })).toBe(false);
  expect(projectHasActiveWork({ status: "blocked", skus: [{ preparationStatus: "blocked", outputs: [] }] })).toBe(false);
  expect(projectHasActiveWork({ status: "draft", skus: [{ preparationStatus: "ready", outputs: [{ status: "running" }] }] })).toBe(true);
  expect(projectHasActiveWork({ status: "draft", skus: [{ preparationStatus: "ready", generationProgress: { status: "running", active: 1, total: 9 }, outputs: [] }] })).toBe(true);
});

test("merges lightweight project progress without dropping heavy project details", () => {
  const project = {
    id: "project-1",
    name: "项目",
    platform: "generic",
    market: "SEA",
    template: "模板",
    size: "1:1",
    status: "draft",
    updatedAt: "old",
    assets: [{ id: "asset-1", name: "a.png", kind: "image" as const }],
    skus: [{
      id: "sku-1",
      name: "商品",
      version: 1,
      assetIds: ["asset-1"],
      facts: "old facts",
      identityLock: "old lock",
      brief: "old brief",
      preparationStatus: "pending",
      preparation: { status: "pending", stage: "N1", current: 1, total: 7, error: "" },
      generationProgress: { status: "idle", total: 0 },
      prompts: [{ slotOrder: 1, slot: "主图", text: "old prompt" }],
      outputs: [],
    }],
  } as Project;

  const next = mergeProjectProgress(project, {
    id: "project-1",
    status: "running",
    updatedAt: "new",
    skus: [{
      id: "sku-1",
      preparationStatus: "preparing",
      preparation: { status: "preparing", stage: "N4", current: 4, total: 7, error: "" },
      generationProgress: { status: "queued", completed: 0, active: 1, failed: 0, total: 9 },
      prompts: [{ slotOrder: 1, slot: "主图", text: "new prompt" }],
      outputs: [{ id: "gen-1", name: "主图", slot: "主图", slotId: "slot-1", slotOrder: 1, attempt: 1, version: 1, status: "queued", reviewStatus: "pending", prompt: "new prompt" }],
    }],
  });

  expect(next.status).toBe("running");
  expect(next.assets).toHaveLength(1);
  expect(next.skus[0].facts).toBe("old facts");
  expect(next.skus[0].preparation?.stage).toBe("N4");
  expect(next.skus[0].prompts?.[0].text).toBe("new prompt");
  expect(next.skus[0].outputs[0].status).toBe("queued");
});
