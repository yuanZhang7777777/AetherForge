import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { exportProject, pauseProject, regenerateGeneration } from "../api";
import { ErrorPanel } from "../layout";
import { displaySlotName } from "../slotDisplay";
import type { Project, ReviewAnnotation } from "../types";
import { currentOutputs } from "../workspace";

const issueTags = [
  ["identity", "商品身份"],
  ["logo_text", "Logo / 文字"],
  ["composition", "构图"],
  ["scene", "场景"],
] as const;

const radius = 0.08;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function circleAt(x: number, y: number): ReviewAnnotation {
  const centerX = clamp(x, radius, 1 - radius);
  const centerY = clamp(y, radius, 1 - radius);
  const round = (value: number) => Number(value.toFixed(4));
  return { kind: "circle", rect: [round(centerX - radius), round(centerY - radius), round(radius * 2), round(radius * 2)], color: "#e11d48", width: 2 };
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

function normalizedCircle(event: MouseEvent<HTMLButtonElement>, image: HTMLImageElement | null) {
  const bounds = event.currentTarget.getBoundingClientRect();
  const box = contentBox(bounds, image);
  if (!box) return null;
  const x = (event.clientX - bounds.left - box.left) / box.width;
  const y = (event.clientY - bounds.top - box.top) / box.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return circleAt(x, y);
}

function markerPosition(annotation: ReviewAnnotation, bounds: DOMRect | undefined, image: HTMLImageElement | null) {
  if (!annotation.rect) return undefined;
  const box = contentBox(bounds, image);
  if (!box) return undefined;
  const [x, y, width, height] = annotation.rect;
  return { left: `${box.left + (x + width / 2) * box.width}px`, top: `${box.top + (y + height / 2) * box.height}px` };
}

export function ResultGrid({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const latestBySku = useMemo(() => project.skus.map((sku) => ({ sku, latest: currentOutputs(sku.outputs) })), [project]);
  const completed = latestBySku.flatMap(({ latest }) => latest.filter((output) => output.status === "completed" && output.imageUrl));
  const completedKey = completed.map((output) => output.id).join("|");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(completed.map((output) => output.id)));
  const [selectedOutputId, setSelectedOutputId] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [annotations, setAnnotations] = useState<ReviewAnnotation[]>([]);
  const [revisionNotice, setRevisionNotice] = useState("");
  const canvas = useRef<HTMLButtonElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const selectedOutput = completed.find((output) => output.id === selectedOutputId) ?? completed[0];
  const selectedOutputName = selectedOutput ? displaySlotName(selectedOutput) : "";

  useEffect(() => {
    setSelectedIds(new Set(completed.map((output) => output.id)));
    setSelectedOutputId((current) => completed.some((output) => output.id === current) ? current : completed[0]?.id ?? "");
  }, [project.id, completedKey]);

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
  const addAnnotation = (annotation: ReviewAnnotation | null) => { if (annotation) setAnnotations((current) => [...current, annotation]); };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      addAnnotation(circleAt(0.5, 0.5));
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
      <section className="space-y-5">
        {latestBySku.map(({ sku, latest }) => (
          <article className="surface p-4" key={sku.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="section-label">商品结果</p>
                <h2 className="mt-1 font-semibold">{sku.name}</h2>
              </div>
              <span className="text-sm text-slate-500">{latest.filter((output) => output.status === "completed").length} / {latest.length || 8} 已完成</span>
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
                    <button className="mt-3 result-preview" onClick={() => setSelectedOutputId(output.id)}>
                      {output.imageUrl ? <img src={output.imageUrl} alt={`${outputName}结果图`} loading="lazy" decoding="async" /> : <span>{output.failureReason ?? "等待结果"}</span>}
                    </button>
                    {output.status === "completed" && output.imageUrl && (
                      <label className="mt-3 flex items-center gap-2 text-sm text-slate-700">
                        <input className="size-4" type="checkbox" checked={selectedIds.has(output.id)} onChange={() => toggle(output.id)} />
                        导出 {outputName} v{output.attempt}
                      </label>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(output.status === "completed" || output.status === "failed") && <button className="text-sm font-semibold text-blue-700 disabled:text-slate-400" disabled={regenerate.isPending} onClick={() => regenerate.mutate(output.id)}>再生成 {outputName}</button>}
                      {["queued", "running"].includes(output.status) && <button className="text-sm font-semibold text-amber-700 disabled:text-slate-400" disabled={pause.isPending} onClick={() => pause.mutate(output.id)}>暂停 {outputName}</button>}
                      {history.map((item) => <button className="text-sm text-slate-500" key={item.id} onClick={() => setSelectedOutputId(item.id)}>历史版本 {displaySlotName(item)} v{item.attempt}</button>)}
                    </div>
                  </article>
                );
              })}
            </div>
          </article>
        ))}
      </section>
      <aside className="surface h-fit p-5">
        <h2 className="font-semibold">选择式 ZIP</h2>
        <p className="mt-2 text-sm text-slate-500">默认勾选每个槽位最新成功图。</p>
        {zip.isError && <ErrorPanel error={zip.error} retry={() => zip.mutate()} />}
        {regenerate.isError && <ErrorPanel error={regenerate.error} retry={() => { if (selectedOutput) regenerate.mutate(selectedOutput.id); }} />}
        {pause.isError && <ErrorPanel error={pause.error} retry={() => { if (selectedOutput) pause.mutate(selectedOutput.id); }} />}
        <button className="primary-button mt-4 w-full" disabled={!selectedIds.size || zip.isPending} onClick={() => zip.mutate()}>
          下载选中 ZIP（{selectedIds.size} 张）
        </button>
        {selectedOutput && (
          <section className="mt-6 border-t border-slate-200 pt-5">
            <p className="section-label">圈选修改</p>
            <h3 className="mt-1 font-semibold">当前修改：{selectedOutputName}</h3>
            <button ref={canvas} type="button" aria-label="在结果图上添加问题圈选" onClick={(event) => addAnnotation(normalizedCircle(event, image.current))} onKeyDown={onKeyDown} className="review-canvas mt-4 min-h-64 border-0 text-left">
              {selectedOutput.imageUrl ? <img ref={image} src={selectedOutput.imageUrl} alt={`当前${selectedOutputName}结果图`} loading="lazy" decoding="async" /> : <span>结果图预览</span>}
              {annotations.map((annotation, index) => annotation.rect ? <i key={`${annotation.rect[0]}-${annotation.rect[1]}-${index}`} className="review-mark" style={markerPosition(annotation, canvas.current?.getBoundingClientRect(), image.current)}>{index + 1}</i> : null)}
            </button>
            {selectedOutput.prompt && (
              <label className="mt-4 block text-sm font-medium text-slate-700">
                <span className="mb-2 block">生成提示词</span>
                <textarea className="min-h-40 text-xs leading-5" readOnly value={selectedOutput.prompt} />
              </label>
            )}
            <fieldset className="mt-4">
              <legend className="text-sm font-medium text-slate-700">问题标签</legend>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {issueTags.map(([value, label]) => (
                  <label className="flex items-center gap-2 text-sm text-slate-700" key={value}>
                    <input type="checkbox" checked={selectedTags.includes(value)} onChange={() => setSelectedTags((tags) => tags.includes(value) ? tags.filter((tag) => tag !== value) : [...tags, value])} />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="mt-4 block text-sm font-medium text-slate-700">
              <span className="mb-2 block">修改说明</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            {revisionNotice && <p className="mt-3 rounded-xl bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700" role="alert">{revisionNotice}</p>}
            <button className="secondary-button mt-3 w-full" onClick={() => setRevisionNotice("修改反馈功能正在开发中")}>提交圈选修改</button>
          </section>
        )}
      </aside>
    </div>
  );
}
