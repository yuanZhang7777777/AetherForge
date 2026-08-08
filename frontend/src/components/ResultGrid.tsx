import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type PointerEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { exportProject, pauseProject, regenerateGeneration, reviseGeneration } from "../api";
import { ErrorPanel } from "../layout";
import { displaySlotName } from "../slotDisplay";
import type { Project, ReviewAnnotation, RevisionInput } from "../types";
import { currentOutputs } from "../workspace";

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function contentBox(bounds: DOMRect | undefined, image: HTMLImageElement | null) {
  if (!bounds?.width || !bounds.height) return null;
  const naturalWidth = image?.naturalWidth || bounds.width;
  const naturalHeight = image?.naturalHeight || bounds.height;
  const scale = Math.min(bounds.width / naturalWidth, bounds.height / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  return { left: (bounds.width - width) / 2, top: (bounds.height - height) / 2, width, height };
}

function round(value: number) {
  return Number(value.toFixed(4));
}

function normalizedPoint(event: PointerEvent<HTMLElement> | MouseEvent<HTMLElement>, image: HTMLImageElement | null) {
  const bounds = event.currentTarget.getBoundingClientRect();
  const box = contentBox(bounds, image);
  if (!box) return null;
  const x = (event.clientX - bounds.left - box.left) / box.width;
  const y = (event.clientY - bounds.top - box.top) / box.height;
  return { x: clamp(x, 0, 1), y: clamp(y, 0, 1) };
}

function rectAnnotation(start: { x: number; y: number }, end: { x: number; y: number }): ReviewAnnotation {
  const x = Math.min(start.x, end.x);
  const y = Math.min(start.y, end.y);
  const width = Math.abs(end.x - start.x);
  const height = Math.abs(end.y - start.y);
  return { kind: "rect", rect: [round(x), round(y), round(width), round(height)], color: "#e11d48", width: 2, note: "" };
}

function usefulAnnotation(annotation: ReviewAnnotation | null) {
  const rect = annotation?.rect;
  return Boolean(rect && rect[2] >= 0.01 && rect[3] >= 0.01);
}

function markerPosition(annotation: ReviewAnnotation, bounds: DOMRect | undefined, image: HTMLImageElement | null) {
  if (!annotation.rect) return undefined;
  const box = contentBox(bounds, image);
  if (!box) return undefined;
  const [x, y, width, height] = annotation.rect;
  return { left: `${box.left + (x + width / 2) * box.width}px`, top: `${box.top + (y + height / 2) * box.height}px` };
}

function markerBox(annotation: ReviewAnnotation, bounds: DOMRect | undefined, image: HTMLImageElement | null) {
  if (!annotation.rect) return undefined;
  const box = contentBox(bounds, image);
  if (!box) return undefined;
  const [x, y, width, height] = annotation.rect;
  return {
    left: `${box.left + x * box.width}px`,
    top: `${box.top + y * box.height}px`,
    width: `${width * box.width}px`,
    height: `${height * box.height}px`,
  };
}

function downloadName(...parts: string[]) {
  const base = parts.join("_").replace(/[<>:"/\\|?*\x00-\x1f]+/g, "").replace(/\s+/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  return `${base || "image"}.png`;
}

export function ResultGrid({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const latestBySku = useMemo(() => project.skus.map((sku) => ({
    sku,
    latest: currentOutputs(sku.outputs),
    latestCompleted: currentOutputs(sku.outputs.filter((output) => output.status === "completed" && output.imageUrl)),
  })), [project]);
  const allOutputs = useMemo(() => project.skus.flatMap((sku) => sku.outputs), [project]);
  const completed = latestBySku.flatMap(({ latestCompleted }) => latestCompleted);
  const allCompleted = useMemo(() => allOutputs.filter((output) => output.status === "completed" && output.imageUrl), [allOutputs]);
  const completedKey = completed.map((output) => output.id).join("|");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(completed.map((output) => output.id)));
  const [selectedOutputId, setSelectedOutputId] = useState("");
  const [revisionTargetId, setRevisionTargetId] = useState("");
  const [description, setDescription] = useState("");
  const [annotations, setAnnotations] = useState<ReviewAnnotation[]>([]);
  const [drawingEnabled, setDrawingEnabled] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftAnnotation, setDraftAnnotation] = useState<ReviewAnnotation | null>(null);
  const [revisionNotice, setRevisionNotice] = useState("");
  const [lightbox, setLightbox] = useState<{ url: string; name: string } | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const selectedOutput = allOutputs.find((output) => output.id === selectedOutputId) ?? completed[0];
  const revisionTarget = allOutputs.find((output) => output.id === revisionTargetId);
  const selectedOutputName = selectedOutput ? displaySlotName(selectedOutput) : "";
  const revisionTargetName = revisionTarget ? displaySlotName(revisionTarget) : "";

  useEffect(() => {
    setSelectedIds(new Set(completed.map((output) => output.id)));
    setSelectedOutputId((current) => completed.some((output) => output.id === current) ? current : completed[0]?.id ?? "");
  }, [project.id, completedKey]);

  useEffect(() => {
    if (!lightbox) return;
    const close = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") setLightbox(null); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [lightbox]);

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["project", project.id] });
    await queryClient.invalidateQueries({ queryKey: ["workspace"] });
  };
  const zip = useMutation({
    mutationFn: () => exportProject(project.id, Array.from(selectedIds)),
    onSuccess: (bundle) => {
      const url = URL.createObjectURL(bundle);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${project.name}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const regenerate = useMutation({ mutationFn: regenerateGeneration, onSuccess: invalidate });
  const revise = useMutation({
    mutationFn: ({ generationId, input }: { generationId: string; input: RevisionInput }) => reviseGeneration(generationId, input),
    onSuccess: async () => {
      setRevisionTargetId("");
      setDescription("");
      setAnnotations([]);
      setDrawingEnabled(false);
      setDragStart(null);
      dragStartRef.current = null;
      setDraftAnnotation(null);
      setRevisionNotice("");
      await invalidate();
    },
  });
  const pause = useMutation({
    mutationFn: (generationId: string) => pauseProject(project.id, { generationIds: [generationId] }),
    onMutate: (generationId) => {
      queryClient.setQueryData<Project>(["project", project.id], (current) => current ? {
        ...current,
        skus: current.skus.map((sku) => ({
          ...sku,
          outputs: sku.outputs.map((output) => output.id === generationId ? { ...output, status: "failed", failureReason: "已暂停，可重新生成" } : output),
        })),
      } : current);
    },
    onSuccess: invalidate,
  });
  const toggle = (id: string) => setSelectedIds((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const updateAnnotationNote = (index: number, note: string) => {
    setAnnotations((current) => current.map((annotation, itemIndex) => itemIndex === index ? { ...annotation, note } : annotation));
  };
  const deleteAnnotation = (index: number) => {
    setAnnotations((current) => current.filter((_annotation, itemIndex) => itemIndex !== index));
  };
  const openRevision = (output: NonNullable<typeof selectedOutput>) => {
    setSelectedOutputId(output.id);
    setRevisionTargetId(output.id);
    setDescription("");
    setAnnotations([]);
    setDrawingEnabled(false);
    setDragStart(null);
    dragStartRef.current = null;
    setDraftAnnotation(null);
    setRevisionNotice("");
  };
  const submitRevision = () => {
    if (!revisionTarget) return;
    const cleanDescription = description.trim();
    const cleanAnnotations = annotations.map((annotation) => ({ ...annotation, note: annotation.note?.trim() ?? "" }));
    if (!cleanDescription && !cleanAnnotations.some((annotation) => annotation.note)) {
      setRevisionNotice("请先填写整体修改说明或标记说明。");
      return;
    }
    revise.mutate({
      generationId: revisionTarget.id,
      input: { issue_tags: [], description: cleanDescription, annotations: cleanAnnotations },
    });
  };
  const downloadSelectedImages = () => {
    allCompleted.filter((output) => selectedIds.has(output.id) && output.imageUrl).forEach((output) => {
      const anchor = document.createElement("a");
      anchor.href = output.imageUrl as string;
      anchor.download = downloadName(project.name, displaySlotName(output), `v${output.attempt}`);
      anchor.click();
    });
  };
  const startDrawing = (event: PointerEvent<HTMLDivElement>) => {
    if (!drawingEnabled) return;
    const point = normalizedPoint(event, image.current);
    if (!point) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragStartRef.current = point;
    setDragStart(point);
    setDraftAnnotation(rectAnnotation(point, point));
  };
  const updateDrawing = (event: PointerEvent<HTMLDivElement> | MouseEvent<HTMLDivElement>) => {
    const start = dragStartRef.current ?? dragStart;
    if (!drawingEnabled || !start) return;
    const point = normalizedPoint(event, image.current);
    if (!point) return;
    setDraftAnnotation(rectAnnotation(start, point));
  };
  const finishDrawing = (event: PointerEvent<HTMLDivElement> | MouseEvent<HTMLDivElement>) => {
    const start = dragStartRef.current ?? dragStart;
    if (!drawingEnabled || !start) return;
    const point = normalizedPoint(event, image.current);
    const annotation = point ? rectAnnotation(start, point) : draftAnnotation;
    if (usefulAnnotation(annotation)) {
      setAnnotations((current) => [...current, annotation as ReviewAnnotation]);
    }
    dragStartRef.current = null;
    setDragStart(null);
    setDraftAnnotation(null);
  };
  const startMouseDrawing = (event: MouseEvent<HTMLDivElement>) => {
    if (!drawingEnabled) return;
    const point = normalizedPoint(event, image.current);
    if (!point) return;
    event.preventDefault();
    dragStartRef.current = point;
    setDragStart(point);
    setDraftAnnotation(rectAnnotation(point, point));
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      <section className="space-y-5">
        {latestBySku.map(({ sku, latest }) => {
          const completedCount = latest.filter((output) => output.status === "completed").length;
          const totalCount = latest.length || 8;
          const completedPercent = Math.round((completedCount / totalCount) * 100);
          return (
          <article className="surface p-4" key={sku.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="section-label">商品结果</p>
                <h2 className="mt-1 font-semibold">{sku.name}</h2>
              </div>
              <span className="text-sm text-slate-500">{completedCount} / {totalCount} 已完成 · {completedPercent}%</span>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {latest.map((output) => {
                const outputName = displaySlotName(output);
                const history = sku.outputs
                  .filter((item) => item.slotId === output.slotId && item.id !== output.id)
                  .sort((left, right) => right.attempt - left.attempt);
                return (
                  <article className="result-card" key={output.id}>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-semibold text-slate-400">{String(output.slotOrder).padStart(2, "0")}</p>
                        <h3 className="font-semibold">{outputName}</h3>
                      </div>
                      <span className={`status status-${output.status}`}>v{output.attempt}</span>
                    </div>
                    <button className="mt-3 result-preview" onClick={() => setSelectedOutputId(output.id)} onDoubleClick={() => { if (output.imageUrl) setLightbox({ url: output.imageUrl, name: outputName }); }}>
                      {output.imageUrl ? <img src={output.imageUrl} alt={`${outputName}结果图`} loading="lazy" decoding="async" /> : <span>{output.failureReason ?? "等待结果"}</span>}
                    </button>
                    {output.status === "completed" && output.imageUrl && (
                      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-700">
                        <label className="flex items-center gap-2">
                          <input className="size-4" type="checkbox" checked={selectedIds.has(output.id)} onChange={() => toggle(output.id)} />
                          导出 {outputName} v{output.attempt}
                        </label>
                        <a className="result-action" href={output.imageUrl} download={downloadName(project.name, sku.name, outputName, `v${output.attempt}`)}>下载 {outputName} v{output.attempt}</a>
                      </div>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {["failed", "canceled"].includes(output.status) && <button className="result-action" disabled={regenerate.isPending} onClick={() => regenerate.mutate(output.id)}>重试失败图 {outputName}</button>}
                      {output.status === "completed" && output.imageUrl && <button className="result-action" disabled={revise.isPending} onClick={() => openRevision(output)}>修改 {outputName} v{output.attempt}</button>}
                      {["queued", "running"].includes(output.status) && <button className="result-action result-action-warning" disabled={pause.isPending} onClick={() => pause.mutate(output.id)}>暂停 {outputName}</button>}
                    </div>
                    {history.length > 0 && (
                      <div className="mt-4">
                        <p className="text-xs font-semibold text-slate-500">历史版本</p>
                        <div className="version-fan" aria-label={`${outputName}历史版本`}>
                          {history.slice(0, 5).map((item, index) => (
                            <div
                              className="version-card"
                              key={item.id}
                              style={{ "--version-index": index } as CSSProperties}
                            >
                              <button className="size-full" type="button" aria-label={`查看历史版本 ${displaySlotName(item)} v${item.attempt}`} onClick={() => setSelectedOutputId(item.id)}>
                                {item.imageUrl ? <img src={item.imageUrl} alt={`${displaySlotName(item)} v${item.attempt} 历史图`} loading="lazy" decoding="async" /> : <span>{item.status}</span>}
                              </button>
                              {item.status === "completed" && item.imageUrl && (
                                <label className="absolute left-1 top-1 grid size-5 place-items-center rounded bg-white/90 shadow" onClick={(event) => event.stopPropagation()}>
                                  <input aria-label={`导出 ${displaySlotName(item)} v${item.attempt}`} className="size-3.5" type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggle(item.id)} />
                                </label>
                              )}
                              <small>v{item.attempt}</small>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </article>
          );
        })}
      </section>
      <aside className="surface h-fit p-5 xl:sticky xl:top-24">
        <h2 className="font-semibold">下载与导出</h2>
        <p className="mt-2 text-sm text-slate-500">默认勾选每个槽位最新成功图，历史版本可单独勾选。</p>
        {zip.isError && <ErrorPanel error={zip.error} retry={() => zip.mutate()} />}
        {regenerate.isError && <ErrorPanel error={regenerate.error} retry={() => { if (selectedOutput) regenerate.mutate(selectedOutput.id); }} />}
        {pause.isError && <ErrorPanel error={pause.error} retry={() => { if (selectedOutput) pause.mutate(selectedOutput.id); }} />}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button className="secondary-button justify-center" type="button" onClick={() => setSelectedIds(new Set(allCompleted.map((output) => output.id)))}>
            勾选全部
          </button>
          <button className="secondary-button justify-center" type="button" onClick={() => setSelectedIds(new Set())}>
            取消勾选
          </button>
        </div>
        <button className="primary-button mt-3 w-full" disabled={!selectedIds.size} onClick={downloadSelectedImages}>
          下载选中图片（{selectedIds.size} 张）
        </button>
        <button className="secondary-button mt-2 w-full" disabled={!selectedIds.size || zip.isPending} onClick={() => zip.mutate()}>
          下载选中 ZIP（{selectedIds.size} 张）
        </button>
        {selectedOutput && (
          <section className="mt-6 border-t border-slate-200 pt-5">
            <p className="section-label">当前图片</p>
            <h3 className="mt-1 font-semibold">{selectedOutputName} v{selectedOutput.attempt}</h3>
            <div className="mt-4 overflow-hidden rounded-2xl bg-slate-100">
              {selectedOutput.imageUrl ? <img src={selectedOutput.imageUrl} alt={`当前${selectedOutputName}结果图`} className="w-full object-contain" loading="lazy" decoding="async" /> : <p className="p-6 text-sm text-slate-500">结果图预览</p>}
            </div>
            {selectedOutput.status === "completed" && selectedOutput.imageUrl && (
              <button className="secondary-button mt-3 w-full" disabled={revise.isPending} onClick={() => openRevision(selectedOutput)}>修改当前图片</button>
            )}
            {selectedOutput.imageUrl && (
              <a className="secondary-button mt-2 w-full" href={selectedOutput.imageUrl} download={downloadName(project.name, selectedOutputName, `v${selectedOutput.attempt}`)}>下载当前图片</a>
            )}
            {selectedOutput.prompt && (
              <label className="mt-4 block text-sm font-medium text-slate-700">
                <span className="mb-2 block">生成提示词</span>
                <textarea className="min-h-40 text-xs leading-5" readOnly value={selectedOutput.prompt} />
              </label>
            )}
          </section>
        )}
      </aside>
      {revisionTarget && (
        <div className="fixed inset-0 z-[80] overflow-y-auto bg-slate-950/70 p-4 md:p-8" role="dialog" aria-modal="true" aria-label={`修改 ${revisionTargetName} v${revisionTarget.attempt}`}>
          <section className="mx-auto max-w-6xl rounded-2xl bg-white p-4 shadow-2xl md:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="section-label">图片修改</p>
                <h2 className="mt-1 text-xl font-semibold">修改 {revisionTargetName} v{revisionTarget.attempt}</h2>
              </div>
              <button className="secondary-button" type="button" onClick={() => setRevisionTargetId("")}>关闭修改</button>
            </div>
            <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
              <section>
                <div
                  ref={canvas}
                  aria-label="在结果图上拖拽框选修改区域"
                  className={`review-canvas ${drawingEnabled ? "review-canvas-drawing" : ""}`}
                  onPointerDown={startDrawing}
                  onPointerMove={updateDrawing}
                  onPointerUp={finishDrawing}
                  onPointerCancel={() => { dragStartRef.current = null; setDragStart(null); setDraftAnnotation(null); }}
                  onMouseDown={startMouseDrawing}
                  onMouseMove={updateDrawing}
                  onMouseUp={finishDrawing}
                >
                  {revisionTarget.imageUrl ? <img ref={image} src={revisionTarget.imageUrl} alt={`${revisionTargetName}待修改结果图`} /> : <span>结果图预览</span>}
                  {[...annotations, ...(draftAnnotation ? [draftAnnotation] : [])].map((annotation, index) => annotation.rect ? (
                    <span key={`${annotation.kind}-${index}`}>
                      <span className={`review-area review-area-${annotation.kind}`} style={markerBox(annotation, canvas.current?.getBoundingClientRect(), image.current)} />
                      {index < annotations.length && <i className="review-mark" style={markerPosition(annotation, canvas.current?.getBoundingClientRect(), image.current)}>{index + 1}</i>}
                    </span>
                  ) : null)}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className={drawingEnabled ? "primary-button" : "secondary-button"} type="button" onClick={() => setDrawingEnabled((current) => !current)}>添加修改区域</button>
                  <button className="secondary-button" type="button" disabled={!annotations.length} onClick={() => setAnnotations((current) => current.slice(0, -1))}>撤销上一步</button>
                  <button className="secondary-button" type="button" disabled={!annotations.length} onClick={() => setAnnotations([])}>清除全部</button>
                </div>
              </section>
              <aside>
                <label className="block text-sm font-medium text-slate-700">
                  <span className="mb-2 block">整体修改说明</span>
                  <textarea aria-label="整体修改说明" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="例如：整体文字放大，商品不变，只优化右下角卖点说明" />
                </label>
                <div className="mt-4 space-y-3">
                  {annotations.map((annotation, index) => (
                    <article className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm font-medium text-slate-700" key={`${annotation.kind}-${index}`}>
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <span>标记 {index + 1}</span>
                        <button className="text-xs font-semibold text-rose-700" type="button" onClick={() => deleteAnnotation(index)}>删除标记 {index + 1}</button>
                      </div>
                      <textarea aria-label={`标记 ${index + 1} 修改说明`} value={annotation.note ?? ""} onChange={(event) => updateAnnotationNote(index, event.target.value)} placeholder="说明这个标记区域要怎么改" />
                    </article>
                  ))}
                </div>
                {revisionNotice && <p className="mt-3 rounded-xl bg-indigo-50 px-3 py-2 text-sm font-semibold text-indigo-700" role="alert">{revisionNotice}</p>}
                {revise.isError && <div className="mt-3"><ErrorPanel error={revise.error} retry={submitRevision} /></div>}
                <button className="primary-button mt-4 w-full" type="button" disabled={revise.isPending} onClick={submitRevision}>{revise.isPending ? "提交中…" : "提交修改生成新版本"}</button>
              </aside>
            </div>
          </section>
        </div>
      )}
      {lightbox && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/85 p-6" role="dialog" aria-modal="true" aria-label={`${lightbox.name} 放大查看`} onClick={() => setLightbox(null)}>
          <button className="absolute right-4 top-4 text-sm font-semibold text-white" onClick={() => setLightbox(null)}>关闭</button>
          <img src={lightbox.url} alt={`${lightbox.name} 放大图`} className="max-h-[88vh] max-w-full rounded-xl object-contain shadow-2xl" onClick={(event) => event.stopPropagation()} />
        </div>
      )}
    </div>
  );
}
