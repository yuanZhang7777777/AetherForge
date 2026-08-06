import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../api";
import { commonMarkets, extraMarkets, platforms } from "../labels";
import type { ClusterUpdateInput, ClusterUpdateResult, ProductAsset, ProductSku } from "../types";
import { PromptEditor } from "./PromptEditor";

type Draft = {
  name: string;
  productFacts: string;
  platformOverride: string;
  marketOverride: string;
};

const stageText: Record<string, string> = {
  N1: "正在识别商品",
  N2: "正在写提示词",
  N3: "正在整理出图请求",
};

// 阶段加权进度：N1=10% N2=80%(=10+70) N3=100%，当前阶段显示其累计百分比下限
const stagePercent: Record<string, number> = {
  N1: 10,
  N2: 80,
  N3: 100,
};

function cleanChineseProductText(value: string) {
  const text = translateKnownProductText(String(value || "").trim());
  if (!text) return "";
  const parts = text
    .split(/[;\n,]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part.replace(/^可见/, "").replace(/^(主要外观|款式\/颜色|风格\/要求|身份保持)[：:]\s*$/, ""))
    .filter(Boolean)
    .map((part) => {
      const phrase = chineseProductPhrase(part);
      return phrase || part;
    });
  return Array.from(new Set(parts)).join("；");
}

function translateKnownProductText(value: string) {
  return String(value || "")
    .replace(/Main appearance\s*:?/gi, "主要外观：")
    .replace(/Style\/Color\s*:?/gi, "款式/颜色：")
    .replace(/Style\/Requirements\s*:?/gi, "风格/要求：")
    .replace(/Identity maintained\s*:?/gi, "身份保持：")
    .replace(/Copper-bowl wooden-handled cutlery/gi, "木柄餐具套装")
    .replace(/visible wooden-handled spoons with tray/gi, "木柄餐具套装")
    .replace(/tray material resembles pressed pulp\/cardboard/gi, "托盘材质像纸浆或纸板")
    .replace(/wooden[- ]handled spoons?/gi, "木柄勺")
    .replace(/wooden[- ]handled cutlery/gi, "木柄餐具")
    .replace(/Yellow plush toy/gi, "黄色毛绒玩偶")
    .replace(/round black eyes/gi, "圆形黑眼睛")
    .replace(/plush texture/gi, "毛绒质感")
    .replace(/yellow plush/gi, "黄色毛绒")
    .replace(/plush toy/gi, "毛绒玩偶")
    .replace(/\brice cooker\b/gi, "电饭锅")
    .replace(/\bdark style\b/gi, "暗黑风格")
    .trim();
}

function chineseProductPhrase(value: string) {
  const text = translateKnownProductText(String(value || "").trim());
  if (/[\u3400-\u9fff]/.test(text)) {
    const cleaned = text.replace(/^可见/, "").replace(/;.*[A-Za-z].*$/, "").trim();
    return cleaned || text;
  }
  const lower = text.toLowerCase();
  if (/(chopstick|utensil|cutlery|wooden spoon|spoon)/.test(lower)) {
    return /(tray|case|set|chopstick|cutlery)/.test(lower) ? "木柄餐具套装" : "木柄餐具";
  }
  if (/(plush|mascot|stuffed|doll|toy|character|costume)/.test(lower)) {
    return /yellow/.test(lower) ? "黄色毛绒玩偶" : "毛绒玩偶";
  }
  if (/(rice cooker|cooker)/.test(lower)) {
    return "电饭锅";
  }
  return text;
}

function uniqueLines(lines: string[]) {
  const seen = new Set<string>();
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => {
      if (seen.has(line)) return false;
      seen.add(line);
      return true;
    })
    .join("\n");
}

function supplementFromSku(sku: ProductSku) {
  const profile = sku.identity?.product_profile;
  const appearances = (sku.identity?.target_appearances ?? [])
    .map((item) => item.label || item.variant_attributes?.join("、") || "")
    .filter(Boolean)
    .join("、");
  const sharedStructure = profile?.shared_structure?.join("；") ?? "";
  const included = profile?.included_items?.join("；") ?? "";
  return uniqueLines([
    cleanChineseProductText(sku.productFacts ?? sku.facts ?? ""),
    profile?.primary_appearance ? `主要外观：${cleanChineseProductText(profile.primary_appearance)}` : "",
    appearances ? `款式/颜色：${cleanChineseProductText(appearances)}` : "",
    sharedStructure ? `结构/材质：${cleanChineseProductText(sharedStructure)}` : "",
    included ? `包含：${cleanChineseProductText(included)}` : "",
    sku.productStyle || sku.brief ? `风格/要求：${cleanChineseProductText(sku.productStyle ?? sku.brief ?? "")}` : "",
    sku.identityLock ? `身份保持：${cleanChineseProductText(sku.identityLock)}` : "",
  ]);
}

function draftFromSku(sku: ProductSku): Draft {
  return {
    name: chineseProductPhrase(sku.name || sku.identity?.product_name || ""),
    productFacts: supplementFromSku(sku),
    platformOverride: sku.overrides?.platform ?? "",
    marketOverride: sku.overrides?.market ?? "",
  };
}

function safePercent(current: number, total: number) {
  if (!total) return 0;
  return Math.round((Math.min(current, total) / total) * 100);
}

function progressText(sku: ProductSku) {
  const generation = sku.generationProgress;
  const generated = generation?.completed ?? generation?.current ?? 0;
  const generationTotal = generation?.total || expectedGenerationTotal(sku);
  const failed = generation?.failed ?? 0;
  const failureText = failed ? ` · 有 ${failed} 张失败` : "";
  if (generation?.active || (generation?.status && !["idle", "completed", "failed"].includes(generation.status) && generated + failed < generationTotal)) return `出图中 · ${generated}/${generationTotal} · ${safePercent(generated, generationTotal)}%${failureText}`;
  if (failed) return `出图已结束 · ${generated}/${generationTotal} · ${safePercent(generated, generationTotal)}%${failureText}`;
  if (generationTotal && generated === generationTotal) return `出图完成 · ${generated}/${generationTotal} · 100%`;
  const preparation = sku.preparation;
  const status = preparation?.status ?? sku.preparationStatus ?? "pending";
  if (status === "ready") return `预备完成 · 100%`;
  if (status === "preparing") {
    const stage = preparation?.stage ?? "";
    const percent = stagePercent[stage];
    if (percent != null) return `${stage ? stageText[stage] ?? "正在处理商品" : "正在预备生成"} · ${percent}%`;
    return `正在预备生成 · ${preparation?.current ?? 0}/${preparation?.total ?? 3}`;
  }
  if (status === "pending" && preparation?.stage && preparation.stage !== "queued") {
    const percent = stagePercent[preparation.stage];
    if (percent != null) return `${stageText[preparation.stage] ?? "正在处理商品"} · ${percent}%`;
    return `${stageText[preparation.stage] ?? "正在处理商品"} · ${preparation?.current ?? 0}/${preparation?.total ?? 3}`;
  }
  if (status === "pending") return `正在预备生成 · 排队中`;
  if (status === "blocked") return `需要补充信息${preparation?.error ? ` · ${friendlyPreparationError(preparation.error)}` : ""}`;
  if (status === "failed") return `预备未完成${preparation?.error ? ` · ${friendlyPreparationError(preparation.error)}` : ""}`;
  return `待预备生成`;
}

function friendlyPreparationError(error: string) {
  if (/Product is being prepared/i.test(error)) return "商品正在处理，完成后再修改或重新生成";
  if (/Cluster changed|refresh before saving/i.test(error)) return "商品信息刚刚更新，请刷新后再保存";
  if (/Product is archived/i.test(error)) return "商品已归档，不能继续修改";
  if (/提示词生成失败/i.test(error)) return "提示词生成失败，请重试预备生成";
  if (/image_role|visible product identity|schema|JSON|observed_identity|N2 may only|owned product reference|placeholder string|must be|must identify|additionalProperties|evidence_refs|fact_refs|reference_plan|Expecting value|DeepSeek/i.test(error)) return "提示词生成失败，请重试预备生成";
  if (/no product|cannot confirm|identity_needs_input|product identity/i.test(error)) return "图片中没有可识别商品，请换图或补充商品信息";
  return error;
}

function progressMeta(sku: ProductSku) {
  const generation = sku.generationProgress;
  const generated = generation?.completed ?? generation?.current ?? 0;
  const generationTotal = generation?.total || expectedGenerationTotal(sku);
  if (generation?.active || (generation?.status && !["idle", "completed", "failed"].includes(generation.status) && generated + (generation.failed ?? 0) < generationTotal)) {
    return { text: progressText(sku), current: generated, total: generationTotal, active: true, percent: safePercent(generated, generationTotal) };
  }
  const preparation = sku.preparation;
  if (["pending", "preparing"].includes(preparation?.status ?? sku.preparationStatus ?? "")) {
    return { text: progressText(sku), current: preparation?.current ?? 0, total: preparation?.total ?? 3, active: true, percent: stagePercent[preparation?.stage ?? ""] };
  }
  return { text: progressText(sku), current: 0, total: 0, active: false };
}

function expectedGenerationTotal(sku: ProductSku) {
  const promptCount = (sku.prompts ?? []).filter((prompt) => !prompt.readOnly).length;
  return promptCount || sku.outputs.length || 9;
}

export function ProductCard({ sku, assets, selected, expanded = false, onOpen = () => undefined, onClose = () => undefined, onSelect, onSave, onReload, onDeleteAsset, onDelete, onPause, disabled }: {
  sku: ProductSku;
  assets: ProductAsset[];
  mergeableAssets?: ProductAsset[];
  selected: boolean;
  expanded?: boolean;
  onOpen?: () => void;
  onClose?: () => void;
  onSelect: (checked: boolean) => void;
  onMerge?: (assetId: string) => void;
  onSave: (payload: ClusterUpdateInput, expectedVersion: number) => Promise<ClusterUpdateResult>;
  onReload: () => Promise<unknown> | void;
  onDeleteAsset: (assetId: string) => void;
  onDelete: () => void;
  onPause?: () => void;
  disabled?: boolean;
}) {
  const droppable = useDroppable({ id: `cluster:${sku.id}`, data: { type: "cluster", clusterId: sku.id }, disabled });
  const [draft, setDraft] = useState(() => draftFromSku(sku));
  const [savedDraft, setSavedDraft] = useState(() => draftFromSku(sku));
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [previewAssetId, setPreviewAssetId] = useState<string | null>(null);
  const currentVersionRef = useRef(sku.version);
  const serverDraftRef = useRef(draftFromSku(sku));
  const label = draft.name.trim() || "未命名商品";
  const nameSourceText = sku.productNameSource === "ai" ? "AI 识别，可修改" : sku.productNameSource === "erp" ? "来自 ERP" : "";
  const progress = progressMeta(sku);
  const previewAsset = assets.find((asset) => asset.id === previewAssetId) ?? assets[0];

  useEffect(() => {
    currentVersionRef.current = sku.version;
  }, [sku.id, sku.version]);
  useEffect(() => {
    if (previewAssetId && !assets.some((asset) => asset.id === previewAssetId)) setPreviewAssetId(null);
  }, [assets, previewAssetId]);
  useEffect(() => {
    const next = draftFromSku(sku);
    const serverChanged = JSON.stringify(next) !== JSON.stringify(serverDraftRef.current);
    serverDraftRef.current = next;
    if (!serverChanged) return; // 服务器值未变：保留用户刚 blur 保存的内容，避免被旧回包覆盖
    setDraft((current) => ({
      name: current.name === savedDraft.name ? next.name : current.name,
      productFacts: current.productFacts === savedDraft.productFacts ? next.productFacts : current.productFacts,
      platformOverride: current.platformOverride === savedDraft.platformOverride ? next.platformOverride : current.platformOverride,
      marketOverride: current.marketOverride === savedDraft.marketOverride ? next.marketOverride : current.marketOverride,
    }));
    setSavedDraft(next);
  }, [sku.id, sku.name, sku.productFacts, sku.facts, sku.productStyle, sku.brief, sku.identityLock, sku.identity, sku.overrides?.platform, sku.overrides?.market, savedDraft]);

  const submit = async () => {
    const payload: ClusterUpdateInput = {};
    if (draft.name !== savedDraft.name) payload.name = draft.name;
    if (draft.productFacts !== savedDraft.productFacts) payload.product_facts = draft.productFacts;
    if (draft.platformOverride !== savedDraft.platformOverride) payload.platform_override = draft.platformOverride || null;
    if (draft.marketOverride !== savedDraft.marketOverride) payload.market_override = draft.marketOverride || null;
    if (!Object.keys(payload).length) return;
    setSaving(true);
    setSaveError("");
    try {
      const result = await onSave(payload, currentVersionRef.current);
      currentVersionRef.current = result.version;
      setSavedDraft(draft);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setSaveError("商品信息已更新，请保留修改后重试");
        void onReload();
      } else setSaveError(error instanceof Error ? friendlyPreparationError(error.message) : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };
  const savePrompt = async (payload: ClusterUpdateInput) => {
    const result = await onSave(payload, currentVersionRef.current);
    currentVersionRef.current = result.version;
    return result;
  };
  return <div className="min-w-0" data-expanded-product={expanded ? sku.id : undefined}>
    <article
      ref={droppable.setNodeRef}
      role="group"
      aria-label={`${label} 商品卡片（可拖拽合并）`}
      className={`surface product-card min-w-0 overflow-hidden ${droppable.isOver ? "ring-2 ring-indigo-500" : ""}`}
      onClick={(event) => { if (!(event.target as HTMLElement).closest("input,select,textarea,button,summary,a")) onOpen(); }}
    >
      <div className="relative block aspect-[4/3] w-full bg-slate-200/50 text-left" aria-label={`${label} 商品主预览`}>
        {previewAsset?.imageUrl ? <img className="relative size-full object-contain" src={previewAsset.imageUrl} alt={`${label} 商品参考图`} loading="lazy" decoding="async" /> : <span className="grid size-full place-items-center text-sm text-slate-400">等待图片</span>}
        <span className="absolute bottom-2 left-2 rounded-full bg-slate-950/80 px-2 py-1 text-xs font-semibold text-white">{assets.length} 张</span>
        <label className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-white/90 px-2 py-1 text-xs font-semibold text-slate-700 shadow-sm"><input aria-label={`选择 ${label}`} className="size-4" type="checkbox" checked={selected} onChange={(event) => onSelect(event.target.checked)} />选择</label>
      </div>
      <div className="flex max-w-full gap-2 overflow-x-auto p-3 pb-2" role="list" aria-label={`${label} 参考图排序`}>
        {assets.map((asset, index) => <DraggableAsset key={asset.id} asset={asset} index={index} active={asset.id === previewAsset?.id} disabled={saving || disabled} onPreview={() => setPreviewAssetId(asset.id)} onDelete={() => onDeleteAsset(asset.id)} />)}
      </div>
      <div className="flex flex-col gap-2 p-3">
        <input aria-label={`商品名称 ${label}`} className="h-9 min-h-9 font-semibold" value={draft.name} placeholder="可不填，预备生成时识别" onChange={(event) => setDraft({ ...draft, name: event.target.value })} onBlur={() => void submit()} />
        {nameSourceText && <p className="text-[11px] text-slate-500">{nameSourceText}</p>}
        <ProductConfigEditor label={label} draft={draft} setDraft={setDraft} onBlur={submit} saving={saving || !!disabled} />
        <textarea aria-label={`补充信息 ${label}`} className="min-h-20 resize-none py-1.5 text-xs" value={draft.productFacts} placeholder="材质、颜色、款式、使用限制、风格要求都写在这里" onChange={(event) => setDraft({ ...draft, productFacts: event.target.value })} onBlur={() => void submit()} />
        {saveError && <p className="text-xs text-amber-700">{saveError}</p>}
        <div className="mt-auto space-y-2 text-xs">
          <div className="grid gap-1"><span className={`block max-w-full break-words leading-5 ${progress.active ? "rounded-lg bg-indigo-50 px-2 py-1 font-semibold text-indigo-700" : /失败|受阻|未完成|补充/.test(progress.text) ? "rounded-lg bg-rose-50 px-2 py-1 text-rose-700" : "text-slate-600"}`} title={progress.text}>{progress.active && <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-indigo-600" />} {progress.text}</span><div className="flex flex-wrap gap-2"><button aria-label={`${label} 详情`} className="w-fit font-semibold text-indigo-700" type="button" onClick={onOpen}>详情</button>{progress.active && onPause && <button aria-label={`暂停 ${label}`} className="w-fit font-semibold text-amber-700" type="button" disabled={disabled} onClick={onPause}>暂停</button>}</div></div>
          {progress.active && <ProgressBar current={progress.current} total={progress.total} percent={progress.percent} />}
        </div>
      </div>
    </article>
    {expanded && <section className="surface product-card-expanded-detail fixed inset-y-4 right-4 z-40 w-[min(720px,calc(100vw-2rem))] overflow-y-auto overscroll-contain p-5 shadow-2xl" role="dialog" aria-modal="false" aria-label={`${label} 商品详情`}>
      <div className="flex items-center justify-between gap-3"><div><p className="section-label">商品信息与生成提示词</p><h2 className="mt-1 text-xl font-semibold">{label}</h2></div><button className="secondary-button" type="button" onClick={onClose}>收起</button></div>
      <ProductInfoEditor label={label} draft={draft} setDraft={setDraft} onBlur={submit} saving={saving || !!disabled} />
      <PromptEditor sku={sku} onSave={savePrompt} disabled={saving || disabled} />
      <button className="mt-4 text-sm font-semibold text-rose-700" type="button" disabled={saving || disabled} onClick={() => { if (window.confirm(`删除“${label}”？有历史结果时只会归档。`)) onDelete(); }}>删除商品</button>
    </section>}
  </div>;
}

function ProductConfigEditor({
  label,
  draft,
  setDraft,
  onBlur,
  saving,
}: {
  label: string;
  draft: Draft;
  setDraft: (draft: Draft) => void;
  onBlur: () => Promise<void>;
  saving?: boolean;
}) {
  const allMarkets = [...commonMarkets, ...extraMarkets];
  return <div className="grid grid-cols-2 gap-2">
    <label className="text-xs font-medium text-slate-500">平台<select aria-label={`商品平台 ${label}`} className="mt-1 h-12 min-h-12 leading-6" value={draft.platformOverride} disabled={saving} onChange={(event) => setDraft({ ...draft, platformOverride: event.target.value })} onBlur={() => void onBlur()}><option value="">跟随项目</option>{platforms.map(([code, text]) => <option key={code} value={code}>{text}</option>)}</select></label>
    <label className="text-xs font-medium text-slate-500">国家<select aria-label={`商品国家 ${label}`} className="mt-1 h-12 min-h-12 leading-6" value={draft.marketOverride} disabled={saving} onChange={(event) => setDraft({ ...draft, marketOverride: event.target.value })} onBlur={() => void onBlur()}><option value="">跟随项目</option>{allMarkets.map(([code, text]) => <option key={code} value={code}>{text}</option>)}</select></label>
  </div>;
}

function ProductInfoEditor({
  label,
  draft,
  setDraft,
  onBlur,
  saving,
}: {
  label: string;
  draft: Draft;
  setDraft: (draft: Draft) => void;
  onBlur: () => Promise<void>;
  saving?: boolean;
}) {
  return <section className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4" role="region" aria-label="商品信息">
    <h3 className="text-sm font-semibold text-slate-800">商品信息</h3>
    <div className="mt-3 grid gap-3">
      <label className="text-xs font-medium text-slate-500">商品名称<input aria-label={`商品名称 ${label}`} className="mt-1" value={draft.name} disabled={saving} onChange={(event) => setDraft({ ...draft, name: event.target.value })} onBlur={() => void onBlur()} /></label>
      <label className="text-xs font-medium text-slate-500">补充信息<textarea aria-label={`补充信息 ${label}`} className="mt-1 min-h-28" value={draft.productFacts} disabled={saving} placeholder="材质、颜色、款式、使用限制、风格要求都写在这里" onChange={(event) => setDraft({ ...draft, productFacts: event.target.value })} onBlur={() => void onBlur()} /></label>
    </div>
  </section>;
}

function DraggableAsset({ asset, index, active, onPreview, onDelete, disabled }: { asset: ProductAsset; index: number; active: boolean; onPreview: () => void; onDelete: () => void; disabled?: boolean }) {
  const draggable = useDraggable({ id: `asset:${asset.id}`, data: { type: "asset", assetId: asset.id }, disabled });
  const droppable = useDroppable({ id: `asset-target:${asset.id}`, data: { type: "asset-target", assetId: asset.id }, disabled });
  const setRef = (node: HTMLElement | null) => { draggable.setNodeRef(node); droppable.setNodeRef(node); };
  return <div className="relative size-12 shrink-0" role="listitem"><button ref={setRef} {...draggable.listeners} {...draggable.attributes} data-dnd-activator aria-label={`查看并拖拽商品参考图 ${index + 1}`} className={`size-12 overflow-hidden rounded-lg border bg-slate-100 active:scale-90 active:opacity-70 ${draggable.isDragging ? "opacity-40" : active ? "border-indigo-500 ring-2 ring-indigo-200" : droppable.isOver ? "border-indigo-500 ring-2 ring-indigo-200" : "border-slate-200"}`} onClick={(event) => { event.stopPropagation(); onPreview(); }}>{asset.imageUrl ? <img className="size-full object-contain" src={asset.imageUrl} alt={`商品参考图 ${index + 1}`} loading="lazy" decoding="async" /> : <span className="grid size-full place-items-center text-xs text-slate-400">待预览</span>}</button>{index === 0 && <span className="pointer-events-none absolute bottom-0.5 left-0.5 rounded bg-slate-950/80 px-1 text-[10px] text-white">主</span>}<button aria-label={`删除商品参考图 ${index + 1}`} className="absolute -right-1 -top-1 grid size-5 place-items-center rounded-full bg-slate-950 text-xs text-white" type="button" disabled={disabled} onClick={(event) => { event.stopPropagation(); if (window.confirm(`删除第 ${index + 1} 张商品参考图？`)) onDelete(); }}>×</button></div>;
}

function ProgressBar({ current, total, percent }: { current: number; total: number; percent?: number }) {
  const safeTotal = total || 1;
  const value = percent ?? Math.round((Math.min(current, safeTotal) / safeTotal) * 100);
  const width = Math.max(12, Math.min(100, value));
  return <div className="progress-track" aria-label="预备生成进度" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}><span className="progress-fill progress-fill-active" style={{ width: `${width}%` }} /></div>;
}
