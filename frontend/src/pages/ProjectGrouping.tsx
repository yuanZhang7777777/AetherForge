import { DndContext, DragOverlay, KeyboardSensor, MeasuringStrategy, PointerSensor, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, deleteAsset, deleteCluster, generateProject, importSkus, mergeAsset, pauseProject, prepareProject, splitAsset, updateCluster, updateProjectSettings, uploadAssets, type UploadResult } from "../api";
import { ImportPanel } from "../components/ImportPanel";
import { ProductCard } from "../components/ProductCard";
import { commonMarkets, extraMarkets, platforms } from "../labels";
import { EmptyState, ErrorPanel, Shell, userErrorMessage } from "../layout";
import { useProjectSnapshot } from "../queries";
import type { ClusterUpdateInput, ImportMode, ProductAsset, ProductConfiguration, ProductSku, Project } from "../types";

function isGlobalError(error: unknown) {
  return !(error instanceof ApiError) || error.authRequired || error.status === 401 || error.status === 403 || error.status >= 500;
}

const REAL_MARKETS = [...commonMarkets, ...extraMarkets].filter(([code]) => code !== "SEA");

function generationSlotOrders(skus: ProductSku[]) {
  const orders = skus.flatMap((sku) => (sku.prompts ?? [])
    .filter((prompt) => !prompt.readOnly)
    .map((prompt) => prompt.slotOrder));
  return Array.from(new Set(orders)).sort((a, b) => a - b);
}

function skuHasActivePreparation(sku: ProductSku) {
  return ["pending", "preparing"].includes(sku.preparation?.status ?? sku.preparationStatus ?? "");
}

function skuHasActiveGeneration(sku: ProductSku) {
  const generation = sku.generationProgress;
  return Boolean(
    (generation?.active ?? 0) > 0
    || ["queued", "running"].includes(generation?.status ?? "")
    || sku.outputs.some((output) => ["queued", "running"].includes(output.status)),
  );
}

export default function ProjectGrouping() {
  const { projectId } = useParams();
  const projectQuery = useProjectSnapshot(projectId);
  const queryClient = useQueryClient();
  const [deselectedIds, setDeselectedIds] = useState<Set<string>>(new Set());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const expandedPointerStartedInside = useRef(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [actionNotice, setActionNotice] = useState("");
  const project = projectQuery.data;
  const needsCountry = Boolean(project && (!project.market || project.market === "SEA"));
  const [countryDraft, setCountryDraft] = useState<string>(REAL_MARKETS[0]?.[0] ?? "TH");
  const [activeDrag, setActiveDrag] = useState<ProductAsset | null>(null);
  const selectedClusters = useMemo(() => project?.skus.filter((sku) => !deselectedIds.has(sku.id)) ?? [], [project, deselectedIds]);
  const selectedPreparing = selectedClusters.some(skuHasActivePreparation);
  const selectedGenerating = selectedClusters.some(skuHasActiveGeneration);
  const selectedActiveWork = selectedPreparing || selectedGenerating;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor));
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["workspace"] });
  };
  const upload = useMutation({ mutationFn: ({ files, mode }: { files: File[]; mode: ImportMode }) => uploadAssets(projectId!, files, mode), onSuccess: async (result) => { setUploadResult(result); await invalidate(); } });
  const skuImport = useMutation({ mutationFn: ({ skus, mode }: { skus: string[]; mode: ImportMode }) => importSkus(projectId!, skus, mode), onSuccess: invalidate });
  const markSelectedPreparing = () => {
    const ids = new Set(selectedClusters.map((sku) => sku.id));
    queryClient.setQueryData<Project>(["project", projectId], (current) => current ? {
      ...current,
      skus: current.skus.map((sku) => ids.has(sku.id) ? {
        ...sku,
        preparationStatus: "preparing",
        preparation: { status: "preparing", stage: "N1", current: 0, total: 3, error: "" },
      } : sku),
    } : current);
  };
  const markSelectedGenerating = () => {
    const ids = new Set(selectedClusters.map((sku) => sku.id));
    const totalBySku = new Map(selectedClusters.map((sku) => [
      sku.id,
      (sku.prompts ?? []).filter((prompt) => !prompt.readOnly).length || sku.generationProgress?.total || 9,
    ]));
    queryClient.setQueryData<Project>(["project", projectId], (current) => current ? {
      ...current,
      status: "queued",
      skus: current.skus.map((sku) => ids.has(sku.id) ? {
        ...sku,
        preparationStatus: sku.preparationStatus === "ready" ? sku.preparationStatus : "preparing",
        preparation: sku.preparationStatus === "ready" ? sku.preparation : { status: "preparing", stage: "N1", current: 0, total: 3, error: "" },
        generationProgress: { status: "queued", current: 0, completed: 0, active: 1, failed: 0, total: totalBySku.get(sku.id) ?? 9 },
      } : sku),
    } : current);
  };
  const markClustersPaused = (clusterIds: string[]) => {
    const ids = new Set(clusterIds);
    queryClient.setQueryData<Project>(["project", projectId], (current) => current ? {
      ...current,
      skus: current.skus.map((sku) => ids.has(sku.id) ? {
        ...sku,
        preparationStatus: ["pending", "preparing"].includes(sku.preparation?.status ?? sku.preparationStatus ?? "") ? "draft" : sku.preparationStatus,
        preparation: ["pending", "preparing"].includes(sku.preparation?.status ?? sku.preparationStatus ?? "")
          ? { status: "draft", stage: "draft", current: 0, total: sku.preparation?.total ?? 3, error: "" }
          : sku.preparation,
        generationProgress: sku.generationProgress ? { ...sku.generationProgress, status: "failed", active: 0 } : sku.generationProgress,
        outputs: sku.outputs.map((output) => ["queued", "running"].includes(output.status) ? { ...output, status: "failed", failureReason: "已暂停，可重新生成" } : output),
      } : sku),
    } : current);
  };
  const rollbackProject = (context?: { previous?: Project | undefined }) => {
    if (context?.previous) queryClient.setQueryData<Project>(["project", projectId], context.previous);
  };
  const prepare = useMutation({
    mutationFn: () => prepareProject(projectId!, selectedClusters.map((sku) => sku.id)),
    onMutate: () => { const previous = queryClient.getQueryData<Project>(["project", projectId]); markSelectedPreparing(); setActionNotice(""); return { previous }; },
    onSuccess: (data) => {
      const items = (data as { items?: { status?: string; code?: string; message?: string }[] } | undefined)?.items ?? [];
      const blocked = items.find((item) => item.status === "blocked");
      if (blocked) {
        setActionNotice(blocked.code === "name_required" ? blocked.message || "请先填写商品名称，再预备生成" : blocked.message || "部分商品无法预备");
        // 有失败项 → refetch 服务器真实状态，避免乐观的「正在预备」盖在未启动的商品上
        return invalidate();
      }
      setActionNotice("");
      // 全部成功：不 invalidate project，避免 refetch 把乐观的「正在预备生成」打回服务器 pending 造成闪变；
      // 真实阶段由 progress 轮询（active 才轮）接管。
      return queryClient.invalidateQueries({ queryKey: ["workspace"] });
    },
    onError: (_error, _variables, context) => rollbackProject(context),
  });
  const generate = useMutation({
    mutationFn: () => generateProject(projectId!, { clusterIds: selectedClusters.map((sku) => sku.id), slotOrders: generationSlotOrders(selectedClusters) }),
    onMutate: () => { const previous = queryClient.getQueryData<Project>(["project", projectId]); markSelectedGenerating(); setActionNotice(""); return { previous }; },
    onSuccess: (data) => {
      const items = (data as { items?: { status?: string; message?: string }[] } | undefined)?.items ?? [];
      const errored = items.filter((item) => item.status === "error");
      if (errored.length) {
        const raw = errored[0]?.message || "";
        const friendly = /prompt not ready|prompt not found/i.test(raw)
          ? "所选商品尚未预备生成，请先点「预备生成」"
          : /quota/i.test(raw)
            ? "今日出图配额已用完，请明天再试"
            : /请先填写商品名称|name_required/i.test(raw)
              ? "请先填写商品名称，再正式生成"
              : raw || "所选商品无法生成，请先预备生成";
        setActionNotice(friendly);
      } else if (items.length && items.every((item) => item.status === "noop")) {
        setActionNotice("所选商品已全部生成，无需重复生成");
      } else {
        setActionNotice("");
      }
      return invalidate();
    },
    onError: (_error, _variables, context) => rollbackProject(context),
  });
  const pause = useMutation({
    mutationFn: (clusterIds: string[]) => pauseProject(projectId!, { clusterIds }),
    onMutate: (clusterIds) => { const previous = queryClient.getQueryData<Project>(["project", projectId]); markClustersPaused(clusterIds); setActionNotice(""); return { previous }; },
    onSuccess: invalidate,
    onError: (_error, _variables, context) => rollbackProject(context),
  });
  const save = useMutation({ mutationFn: ({ skuId, expectedVersion, payload }: { skuId: string; expectedVersion: number; payload: ClusterUpdateInput }) => updateCluster(skuId, expectedVersion, payload), onSuccess: invalidate });
  const removeAsset = useMutation({ mutationFn: deleteAsset, onSuccess: invalidate });
  const removeCluster = useMutation({ mutationFn: deleteCluster, onSuccess: invalidate });
  const saveSettings = useMutation({ mutationFn: (input: ProductConfiguration) => updateProjectSettings(projectId!, input), onSuccess: invalidate });
  const confirmCountry = async () => {
    if (!project || !countryDraft) return;
    await saveSettings.mutateAsync({
      platform: project.defaultConfig?.platform || project.platform?.toLowerCase() || "generic",
      market: countryDraft,
      sellerTier: project.defaultConfig?.sellerTier ?? "general",
      size: project.defaultConfig?.size || project.size || "1:1",
      resolution: (project.defaultConfig?.resolution || project.resolution || "1k").toLowerCase(),
      globalPrompt: project.defaultConfig?.globalPrompt || "",
      aiRecognitionEnabled: project.defaultConfig?.aiRecognitionEnabled ?? false,
    });
  };
  const reorganize = useMutation({
    onMutate: async ({ activeId, overId }) => {
      await queryClient.cancelQueries({ queryKey: ["project", projectId] });
      const previous = queryClient.getQueryData<Project>(["project", projectId]);
      queryClient.setQueryData<Project>(["project", projectId], (current) => {
        const assetId = activeId.startsWith("asset:") ? activeId.slice(6) : "";
        if (!current || !assetId) return current;
        const source = current.skus.find((sku) => sku.assetIds.includes(assetId));
        const overAssetId = overId.startsWith("asset-target:") ? overId.slice(13) : "";
        const target = overAssetId ? current.skus.find((sku) => sku.assetIds.includes(overAssetId)) : overId.startsWith("cluster:") ? current.skus.find((sku) => sku.id === overId.slice(8)) : null;
        if (!source || !target || (source.id !== target.id && target.assetIds.includes(assetId))) return current;
        const asset = current.assets.find((item) => item.id === assetId) ?? source.assets?.find((item) => item.id === assetId);
        const skus = current.skus.map((sku) => {
          if (sku.id === source.id && sku.id === target.id) {
            const nextIds = sku.assetIds.filter((id) => id !== assetId);
            const insertAt = overAssetId ? nextIds.indexOf(overAssetId) : nextIds.length;
            nextIds.splice(insertAt < 0 ? nextIds.length : insertAt, 0, assetId);
            const byId = new Map((sku.assets ?? []).map((item) => [item.id, item]));
            return { ...sku, assetIds: nextIds, assets: nextIds.map((id) => byId.get(id)).filter((item): item is ProductAsset => Boolean(item)) };
          }
          if (sku.id === source.id) return { ...sku, assetIds: sku.assetIds.filter((id) => id !== assetId), assets: sku.assets?.filter((item) => item.id !== assetId) };
          if (sku.id === target.id) {
            const nextIds = sku.assetIds.filter((id) => id !== assetId);
            const insertAt = overAssetId ? nextIds.indexOf(overAssetId) : nextIds.length;
            nextIds.splice(insertAt < 0 ? nextIds.length : insertAt, 0, assetId);
            const byId = new Map([...(sku.assets ?? []), asset].filter((item): item is ProductAsset => Boolean(item)).map((item) => [item.id, item]));
            return { ...sku, assetIds: nextIds, assets: nextIds.map((id) => byId.get(id)).filter((item): item is ProductAsset => Boolean(item)) };
          }
          return sku;
        }).filter((sku) => sku.assetIds.length);
        return { ...current, skus };
      });
      return { previous };
    },
    mutationFn: async ({ activeId, overId }: { activeId: string; overId: string }) => {
      if (activeId.startsWith("asset:") && overId === "blank-grid") return splitAsset(activeId.slice(6));
      if (activeId.startsWith("asset:") && overId.startsWith("asset-target:")) {
        const assetId = activeId.slice(6);
        const overAssetId = overId.slice(13);
        const source = project!.skus.find((sku) => sku.assetIds.includes(assetId));
        const target = project!.skus.find((sku) => sku.assetIds.includes(overAssetId));
        if (!source || !target) return;
        if (source.id !== target.id) return mergeAsset(target.id, assetId, target.version);
        const next = source.assetIds.filter((id) => id !== assetId);
        next.splice(next.indexOf(overAssetId), 0, assetId);
        if (next.every((id, index) => id === source.assetIds[index])) return;
        return updateCluster(source.id, source.version, { asset_order: next });
      }
      if (!overId.startsWith("cluster:")) return;
      const target = project!.skus.find((sku) => sku.id === overId.slice(8));
      if (!target) return;
      if (activeId.startsWith("asset:")) {
        const assetId = activeId.slice(6);
        if (target.assetIds.includes(assetId)) return;
        return mergeAsset(target.id, assetId, target.version);
      }
      if (!activeId.startsWith("cluster:")) return;
      const source = project!.skus.find((sku) => sku.id === activeId.slice(8));
      if (!source || source.id === target.id) return;
      if (source.assetIds.length + target.assetIds.length > 16) throw new ApiError(400, "合并后最多保留 16 张商品参考图");
      let version = target.version;
      for (const assetId of source.assetIds) {
        await mergeAsset(target.id, assetId, version);
        version += 1;
      }
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(["project", projectId], context.previous);
    },
    onSettled: invalidate,
  });

  useEffect(() => {
    if (!expandedId) return;
    const markPointerStart = (event: PointerEvent) => {
      const target = event.target as HTMLElement;
      expandedPointerStartedInside.current = Boolean(target.closest(`[data-expanded-product="${expandedId}"]`));
    };
    const consumeOutsideClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest(`[data-expanded-product="${expandedId}"]`)) return;
      if (expandedPointerStartedInside.current) {
        expandedPointerStartedInside.current = false;
        return;
      }
      // 点击另一张商品卡（详情/选择等）→ 吞掉点击并关闭当前卡，避免误切到另一张卡
      if (target.closest('[role="group"]')) {
        event.preventDefault();
        event.stopPropagation();
        setExpandedId(null);
        return;
      }
      // 工具栏/浮动动作条等可交互控件放行不吞不关，否则展开卡片时第一次点「正式生成」
      // 会被吞掉 → 只关卡不触发，要点两次才生效。
      if (target.closest("button,a,input,select,textarea,summary")) return;
      setExpandedId(null);
    };
    document.addEventListener("pointerdown", markPointerStart, true);
    document.addEventListener("click", consumeOutsideClick, true);
    return () => {
      document.removeEventListener("pointerdown", markPointerStart, true);
      document.removeEventListener("click", consumeOutsideClick, true);
    };
  }, [expandedId]);

  if (projectQuery.isLoading) return <Shell><p className="text-sm text-slate-500">正在读取项目…</p></Shell>;
  if (projectQuery.isError || !project) return <Shell><ErrorPanel error={projectQuery.error ?? new Error("项目快照为空")} retry={() => void projectQuery.refetch()} /></Shell>;

  const onDragStart = (event: DragStartEvent) => {
    const id = String(event.active.id);
    if (!id.startsWith("asset:")) return;
    const assetId = id.slice(6);
    const asset = (project?.skus ?? []).flatMap((sku) => sku.assets ?? []).find((item) => item.id === assetId)
      ?? (project?.assets ?? []).find((item) => item.id === assetId);
    setActiveDrag(asset ?? null);
  };
  const onDragEnd = (event: DragEndEvent) => {
    setActiveDrag(null);
    if (event.over) reorganize.mutate({ activeId: String(event.active.id), overId: String(event.over.id) });
  };
  const errors = [upload.error, skuImport.error, prepare.error, generate.error, pause.error, reorganize.error, save.error, removeAsset.error, removeCluster.error, saveSettings.error].filter(Boolean);
  const localError = errors.find((error) => !isGlobalError(error));
  const globalError = errors.find(isGlobalError);
  const actionBusy = upload.isPending || skuImport.isPending || prepare.isPending || generate.isPending || pause.isPending || reorganize.isPending || removeAsset.isPending || removeCluster.isPending;
  const nameRequiredNotice = /请先填写商品名称/.test(actionNotice);

  return <Shell>
    {needsCountry && (
      <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="选择目标国家">
        <div className="w-[min(28rem,calc(100vw-2rem))] rounded-2xl border border-white/70 bg-white/80 p-6 shadow-2xl backdrop-blur-xl">
          <h2 className="mb-1 text-lg font-bold tracking-tight">选择目标国家</h2>
          <p className="mb-4 text-sm text-slate-500">进入项目前请先选择一次目标国家，卖点规划与文案会按该国语言生成。</p>
          <label className="mb-4 block text-xs font-medium text-slate-500">国家<select aria-label="目标国家" className="mt-1" value={countryDraft} onChange={(event) => setCountryDraft(event.target.value)}>{REAL_MARKETS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
          <div className="flex justify-end"><button className="primary-button min-h-9 px-4" type="button" disabled={saveSettings.isPending || !countryDraft} onClick={() => void confirmCountry()}>{saveSettings.isPending ? "保存中…" : "确认"}</button></div>
        </div>
      </div>
    )}
    <ProjectToolbar project={project} pending={saveSettings.isPending} onSave={(input) => saveSettings.mutateAsync(input)} />
    <div className="mb-5"><ImportPanel disabled={actionBusy} aiRecognitionEnabled={project.defaultConfig?.aiRecognitionEnabled ?? false} onAiRecognitionChange={(checked) => saveSettings.mutateAsync({ platform: project.defaultConfig?.platform || project.platform?.toLowerCase() || "generic", market: project.defaultConfig?.market || project.market || "SEA", sellerTier: project.defaultConfig?.sellerTier ?? "general", size: project.defaultConfig?.size || project.size || "1:1", resolution: (project.defaultConfig?.resolution || project.resolution || "1k").toLowerCase(), globalPrompt: project.defaultConfig?.globalPrompt || "", aiRecognitionEnabled: checked })} onUpload={(files, mode) => upload.mutateAsync({ files, mode })} onSkuImport={(skus, mode) => skuImport.mutateAsync({ skus, mode })} onImported={() => undefined} /></div>
    {uploadResult && <div className="mb-5 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">成功导入 {uploadResult.asset_count} 个素材{uploadResult.rejected.length ? `，${uploadResult.rejected.length} 个未导入` : ""}。</div>}
    {localError instanceof ApiError && <p className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{userErrorMessage(localError)}</p>}
    {actionNotice && <p className={`mb-5 rounded-xl border px-4 py-3 text-sm ${nameRequiredNotice ? "border-red-200 bg-red-50 font-semibold text-red-700" : "border-indigo-200 bg-indigo-50 text-indigo-700"}`}>{actionNotice}</p>}
    {globalError && <div className="mb-5"><ErrorPanel error={globalError} /></div>}
    <DndContext sensors={sensors} measuring={{ droppable: { strategy: MeasuringStrategy.BeforeDragging } }} onDragStart={onDragStart} onDragCancel={() => setActiveDrag(null)} onDragEnd={onDragEnd}><ProductGrid>{project.skus.map((sku) => {
      const assets = sku.assets ?? project.assets.filter((asset) => sku.assetIds.includes(asset.id));
      return <ProductCard key={sku.id} sku={sku} assets={assets} selected={!deselectedIds.has(sku.id)} expanded={expandedId === sku.id} disabled={removeAsset.isPending || removeCluster.isPending} onOpen={() => setExpandedId(sku.id)} onClose={() => setExpandedId(null)} onSave={(payload, expectedVersion) => save.mutateAsync({ skuId: sku.id, expectedVersion, payload })} onReload={() => projectQuery.refetch()} onDeleteAsset={(assetId) => removeAsset.mutate(assetId)} onDelete={() => removeCluster.mutate(sku.id)} onPause={() => pause.mutate([sku.id])} onSelect={(next) => setDeselectedIds((current) => { const copy = new Set(current); if (next) copy.delete(sku.id); else copy.add(sku.id); return copy; })} />;
    })}</ProductGrid>
      <DragOverlay dropAnimation={null}>
        {activeDrag?.imageUrl ? <div className="grid size-16 place-items-center overflow-hidden rounded-lg border border-indigo-500 bg-white shadow-xl ring-2 ring-indigo-200"><img className="size-full object-contain" src={activeDrag.imageUrl} alt="拖拽中的商品参考图" /></div> : null}
      </DragOverlay>
    </DndContext>
    {!project.skus.length && <EmptyState title="还没有商品素材" description="在上方导入图片、文件夹或 ERP SKU。" />}
    <FloatingActions projectId={project.id} selectedCount={selectedClusters.length} busy={actionBusy} preparing={selectedPreparing} generating={selectedGenerating} activeWork={selectedActiveWork} onSelectAll={() => setDeselectedIds(new Set())} onDeselectAll={() => setDeselectedIds(new Set(project.skus.map((sku) => sku.id)))} onInvert={() => setDeselectedIds(new Set(project.skus.filter((sku) => !deselectedIds.has(sku.id)).map((sku) => sku.id)))} onPrepare={() => { if (!selectedActiveWork) prepare.mutate(); }} onGenerate={() => { if (!selectedActiveWork) generate.mutate(); }} onPause={() => { if (selectedActiveWork) pause.mutate(selectedClusters.map((sku) => sku.id)); }} />
  </Shell>;
}

function ProductGrid({ children }: { children: ReactNode }) {
  const blank = useDroppable({ id: "blank-grid", data: { type: "blank" } });
  return <section ref={blank.setNodeRef} className={`product-card-grid min-h-56 rounded-2xl ${blank.isOver ? "bg-indigo-50/60" : ""}`} aria-label="商品分组网格">{children}</section>;
}

function ProjectToolbar({ project, pending, onSave }: { project: { id: string; name: string; defaultConfig?: ProductConfiguration; platform: string; market: string; size: string; resolution?: string }; pending: boolean; onSave: (input: ProductConfiguration) => Promise<unknown> }) {
  const allMarkets = [...commonMarkets, ...extraMarkets];
  const initial = () => ({
    platform: project.defaultConfig?.platform || project.platform?.toLowerCase() || "generic",
    market: project.defaultConfig?.market || project.market || "SEA",
    sellerTier: project.defaultConfig?.sellerTier ?? "general" as const,
    size: project.defaultConfig?.size || project.size || "1:1",
    resolution: (project.defaultConfig?.resolution || project.resolution || "1k").toLowerCase(),
    globalPrompt: project.defaultConfig?.globalPrompt || "",
    aiRecognitionEnabled: project.defaultConfig?.aiRecognitionEnabled ?? false,
  });
  const [draft, setDraft] = useState<ProductConfiguration>(initial);
  const [saved, setSaved] = useState<ProductConfiguration>(initial);
  const pendingSaved = useRef<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  useEffect(() => {
    const next = initial();
    const serialized = JSON.stringify(next);
    if (pendingSaved.current && pendingSaved.current !== serialized) return;
    if (pendingSaved.current === serialized) pendingSaved.current = null;
    if (!dirty) { setDraft(next); setSaved(next); }
  }, [project.defaultConfig, project.platform, project.market, project.size, project.resolution, dirty]);
  const save = async (next: ProductConfiguration) => {
    setDraft(next);
    try {
      await onSave(next);
      pendingSaved.current = JSON.stringify(next);
      setSaved(next);
    } catch {
      // The mutation error is rendered by the page; keep this draft dirty for retry.
    }
  };
  return <section className="surface mb-3 p-2" aria-label="项目工具栏">
    <div className="flex flex-wrap items-end gap-2">
      <h1 className="mr-1 min-w-28 max-w-44 self-center truncate text-lg font-bold tracking-tight" title={project.name}>{project.name}</h1>
      <fieldset className="shrink-0"><legend className="mb-1 text-xs font-medium text-slate-500">平台</legend><div className="flex flex-nowrap gap-1">{platforms.map(([code, label]) => <button key={code} aria-pressed={draft.platform === code} className={`toolbar-choice whitespace-nowrap ${draft.platform === code ? "toolbar-choice-active" : ""}`} type="button" disabled={pending} onClick={() => void save({ ...draft, platform: code })}>{label}</button>)}</div></fieldset>
      <label className="w-40 text-xs font-medium text-slate-500">国家<select aria-label="项目国家" className="mt-1" value={draft.market} onChange={(event) => void save({ ...draft, market: event.target.value })}>{allMarkets.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
      <label className="w-24 text-xs font-medium text-slate-500">比例<select aria-label="图片比例" className="mt-1" value={draft.size} onChange={(event) => void save({ ...draft, size: event.target.value })}><option value="1:1">1:1</option><option value="3:4">3:4</option></select></label>
      <label className="w-24 text-xs font-medium text-slate-500">分辨率<select aria-label="图片分辨率" className="mt-1" value={draft.resolution} onChange={(event) => void save({ ...draft, resolution: event.target.value })}><option value="1k">1K</option><option value="2k">2K</option></select></label>
      <label className="min-w-52 flex-1 text-xs font-medium text-slate-500">项目风格提示词<textarea aria-label="项目风格提示词" className="mt-1 min-h-9 max-h-24 resize-y py-1.5" value={draft.globalPrompt} placeholder="全项目默认提示词（选填）" onChange={(event) => setDraft({ ...draft, globalPrompt: event.target.value })} onBlur={() => { if (dirty) void save(draft); }} /></label>
    </div>
  </section>;
}

function FloatingActions({ projectId, selectedCount, busy, preparing, generating, activeWork, onSelectAll, onDeselectAll, onInvert, onPrepare, onGenerate, onPause }: { projectId: string; selectedCount: number; busy: boolean; preparing: boolean; generating: boolean; activeWork: boolean; onSelectAll: () => void; onDeselectAll: () => void; onInvert: () => void; onPrepare: () => void; onGenerate: () => void; onPause: () => void }) {
  return <div className="fixed bottom-5 right-5 z-50 flex max-w-[calc(100vw-2.5rem)] flex-wrap items-center gap-2 rounded-2xl border border-white/70 bg-white/85 p-2 shadow-2xl shadow-indigo-950/10 backdrop-blur-xl" aria-label="滚动常驻生成动作">
    <button className="toolbar-choice min-h-9 px-3" type="button" onClick={onSelectAll}>全选</button>
    <button className="toolbar-choice min-h-9 px-3" type="button" onClick={onDeselectAll}>取消全选</button>
    <button className="toolbar-choice min-h-9 px-3" type="button" onClick={onInvert}>反选</button>
    <span className="px-2 text-xs font-semibold text-slate-600">已选 {selectedCount}</span>
    <button className="secondary-button min-h-9 px-3" type="button" disabled={busy || activeWork || !selectedCount} onClick={onPrepare}>预备生成（{selectedCount}）</button>
    <button className="primary-button min-h-9 px-3" type="button" disabled={busy || activeWork || !selectedCount} title={preparing ? "预备生成完成后才能正式生成" : generating ? "已有出图任务正在执行" : undefined} onClick={onGenerate}>正式生成（{selectedCount}）</button>
    <button className="secondary-button min-h-9 px-3" type="button" disabled={busy || !activeWork || !selectedCount} onClick={onPause}>暂停所选（{selectedCount}）</button>
    <Link className="secondary-button min-h-9 px-3" to={`/projects/${projectId}/results`}>生产结果</Link>
  </div>;
}
