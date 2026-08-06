import type { WorkspaceSnapshot } from "./types";

const image = (name: string, color: string) =>
  `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640" viewBox="0 0 640 640"><rect width="640" height="640" fill="${color}"/><rect x="155" y="100" width="330" height="400" rx="48" fill="#fff"/><rect x="190" y="140" width="260" height="76" rx="24" fill="#172554"/><rect x="206" y="245" width="228" height="210" rx="32" fill="#cbd5e1"/><text x="320" y="290" text-anchor="middle" font-family="Arial" font-size="26" fill="#0f172a">${name}</text></svg>`,
  )}`;

export const developmentWorkspace: WorkspaceSnapshot = {
  projects: [
    {
      id: "project-demo",
      name: "夏日家居上新",
      platform: "Shopee",
      market: "SG",
      configurationStatus: "configured",
      defaultConfig: { platform: "shopee", market: "SG", sellerTier: "general", size: "1:1", resolution: "1k", globalPrompt: "" },
      template: "商品基础套图",
      size: "1:1",
      resolution: "1k",
      status: "running",
      updatedAt: "10 分钟前",
      assets: [
        { id: "asset-lamp-main", name: "desk-lamp-main.png", kind: "image", imageUrl: image("桌面灯", "#dbeafe") },
        { id: "asset-lamp-side", name: "desk-lamp-side.png", kind: "image", imageUrl: image("侧面图", "#e0f2fe") },
        { id: "asset-chair-main", name: "chair-main.png", kind: "image", imageUrl: image("单椅", "#fef3c7") },
      ],
      skus: [
        {
          id: "sku-lamp",
          name: "桌面护眼灯",
          version: 1,
          assetIds: ["asset-lamp-main", "asset-lamp-side"],
          facts: "可调节灯臂，暖白双色光，USB-C 供电。",
          identityLock: "保持深蓝色灯头、金属细杆和底座比例，不增加按钮或文字。",
          brief: "明亮的极简书桌场景，展示深蓝色护眼灯，柔和晨光，商品结构与颜色保持一致。",
          outputs: [
            { id: "output-lamp-main", name: "白底主图", slot: "主图", slotId: "lamp-main", slotOrder: 1, attempt: 1, status: "completed", reviewStatus: "pending", version: 1, imageUrl: image("主图", "#eff6ff") },
            { id: "output-lamp-scene", name: "书桌场景", slot: "场景图", slotId: "lamp-scene", slotOrder: 2, attempt: 1, status: "running", reviewStatus: "pending", version: 1, imageUrl: image("场景", "#ede9fe") },
            { id: "output-lamp-detail", name: "灯头细节", slot: "细节图", slotId: "lamp-detail", slotOrder: 3, attempt: 1, status: "queued", reviewStatus: "pending", version: 1 },
          ],
        },
        {
          id: "sku-chair",
          name: "北欧单椅",
          version: 1,
          assetIds: ["asset-chair-main"],
          facts: "浅橡木椅脚，米白色软包坐垫。",
          identityLock: "保持椅脚数量、米白软包颜色和靠背弧度。",
          brief: "通透客厅场景中的北欧单椅，保留材质纹理和真实比例。",
          outputs: [
            { id: "output-chair-main", name: "白底主图", slot: "主图", slotId: "chair-main", slotOrder: 1, attempt: 1, status: "completed", reviewStatus: "accepted", version: 1, imageUrl: image("主图", "#fff7ed") },
            { id: "output-chair-scene", name: "客厅场景", slot: "场景图", slotId: "chair-scene", slotOrder: 2, attempt: 1, status: "failed", reviewStatus: "pending", version: 1, failureReason: "场景服务暂时不可用" },
          ],
        },
      ],
    },
  ],
};
