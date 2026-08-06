import { useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { submitReview } from "../api";
import { EmptyState, ErrorPanel, PageHeading, Shell } from "../layout";
import { useWorkspaceSnapshot } from "../queries";
import { displaySlotName } from "../slotDisplay";
import type { ReviewAnnotation, ReviewDecision, ReviewInput } from "../types";
import { currentOutputs } from "../workspace";

const issueTags = [
  ["identity", "商品身份"],
  ["logo_text", "Logo / 文字"],
  ["model", "模特"],
  ["color", "颜色"],
  ["composition", "构图"],
  ["scene", "场景"],
  ["platform_rule", "平台规则"],
  ["style", "风格"],
  ["other", "其他"],
] as const;

type ReviewRequest = {
  generationId: string;
  projectId: string;
  input: ReviewInput;
};

const radius = 0.08;

type ContentBox = { left: number; top: number; width: number; height: number };

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function circleAt(x: number, y: number): ReviewAnnotation {
  const centerX = clamp(x, radius, 1 - radius);
  const centerY = clamp(y, radius, 1 - radius);
  const round = (value: number) => Number(value.toFixed(4));
  return {
    kind: "circle",
    rect: [round(centerX - radius), round(centerY - radius), round(radius * 2), round(radius * 2)],
    color: "#e11d48",
    width: 2,
  };
}

function contentBox(bounds: DOMRect | undefined, image: HTMLImageElement | null): ContentBox | null {
  if (!bounds?.width || !bounds.height) return null;
  const naturalWidth = image?.naturalWidth || bounds.width;
  const naturalHeight = image?.naturalHeight || bounds.height;
  const scale = Math.min(bounds.width / naturalWidth, bounds.height / naturalHeight);
  const contentWidth = naturalWidth * scale;
  const contentHeight = naturalHeight * scale;
  return {
    left: (bounds.width - contentWidth) / 2,
    top: (bounds.height - contentHeight) / 2,
    width: contentWidth,
    height: contentHeight,
  };
}

function normalizedCircle(event: MouseEvent<HTMLButtonElement>, image: HTMLImageElement | null): ReviewAnnotation | null {
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
  return {
    left: `${box.left + (x + width / 2) * box.width}px`,
    top: `${box.top + (y + height / 2) * box.height}px`,
  };
}

function snapshotInput(decision: ReviewDecision, tags: string[], description: string, annotations: ReviewAnnotation[]): ReviewInput {
  return {
    decision,
    issue_tags: [...tags],
    description: description.trim(),
    annotations: annotations.map((annotation) => ({
      ...annotation,
      points: annotation.points?.map((point) => [...point]),
      rect: annotation.rect ? [...annotation.rect] as [number, number, number, number] : undefined,
    })),
  };
}

export default function Review() {
  const workspace = useWorkspaceSnapshot();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [annotations, setAnnotations] = useState<ReviewAnnotation[]>([]);
  const [lastRequest, setLastRequest] = useState<ReviewRequest | null>(null);
  const canvas = useRef<HTMLButtonElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const candidates = useMemo(() => workspace.data?.projects.flatMap((project) => project.skus.flatMap((sku) => currentOutputs(sku.outputs).filter((output) => output.status === "completed" && output.reviewStatus === "pending").map((output) => ({ project, sku, output })))) ?? [], [workspace.data]);
  const selected = candidates.find((candidate) => candidate.output.id === selectedId) ?? candidates[0];
  const review = useMutation({
    mutationFn: (request: ReviewRequest) => submitReview(request.generationId, request.input),
    onSuccess: async (_result, request) => {
      setDescription("");
      setSelectedTags([]);
      setAnnotations([]);
      setLastRequest(null);
      await queryClient.invalidateQueries({ queryKey: ["workspace"] });
      await queryClient.invalidateQueries({ queryKey: ["project", request.projectId] });
    },
  });
  if (workspace.isLoading) return <Shell><PageHeading eyebrow="人工审核" title="审核中心" /></Shell>;
  if (workspace.isError || !workspace.data) return <Shell><PageHeading eyebrow="人工审核" title="审核中心" /><ErrorPanel error={workspace.error ?? new Error("项目快照为空")} retry={() => void workspace.refetch()} /></Shell>;
  if (!selected) return <Shell><PageHeading eyebrow="人工审核" title="审核中心" /><EmptyState title="没有待审核结果" description="生成完成的商品图会在这里等待确认。" /></Shell>;
  const canRequestChanges = selectedTags.length > 0 || description.trim().length > 0;
  const addAnnotation = (annotation: ReviewAnnotation | null) => { if (annotation) setAnnotations((current) => [...current, annotation]); };
  const submit = (decision: ReviewDecision) => {
    if (decision === "changes_requested" && !canRequestChanges) return;
    const request = {
      generationId: selected.output.id,
      projectId: selected.project.id,
      input: snapshotInput(decision, selectedTags, description, annotations),
    };
    setLastRequest(request);
    review.mutate(request);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      addAnnotation(circleAt(0.5, 0.5));
    }
  };
  return <Shell><PageHeading eyebrow="人工审核" title="审核中心" />{review.isError && <ErrorPanel error={review.error} retry={() => { if (lastRequest) review.mutate(lastRequest); }} />}<div className="grid gap-6 xl:grid-cols-[270px_minmax(0,1fr)_300px]"><aside className="surface p-3"><p className="section-label px-2 py-2">待判断输出图</p>{candidates.map((candidate) => <button key={candidate.output.id} onClick={() => { setSelectedId(candidate.output.id); setAnnotations([]); setSelectedTags([]); setDescription(""); }} className={`review-item ${selected.output.id === candidate.output.id ? "review-item-active" : ""}`}><span>{candidate.sku.name}</span><small>{displaySlotName(candidate.output)} · v{candidate.output.attempt}</small></button>)}</aside><section className="surface p-5"><div className="flex items-center justify-between"><div><p className="section-label">点击结果图圈选问题</p><h2 className="mt-1 font-semibold">{selected.sku.name} · {displaySlotName(selected.output)}</h2></div><span className="status status-completed">待审核</span></div><button ref={canvas} type="button" aria-label="在结果图上添加问题圈选" onClick={(event) => addAnnotation(normalizedCircle(event, image.current))} onKeyDown={onKeyDown} className="review-canvas mt-5 border-0 text-left">{selected.output.imageUrl ? <img ref={image} src={selected.output.imageUrl} alt="待审核结果" /> : <span>结果图预览</span>}{annotations.map((annotation, index) => annotation.rect ? <i key={`${annotation.rect[0]}-${annotation.rect[1]}-${index}`} className="review-mark" style={markerPosition(annotation, canvas.current?.getBoundingClientRect(), image.current)}>{index + 1}</i> : null)}</button></section><aside className="surface p-5"><p className="section-label">审核结论</p><p className="mt-2 text-sm text-slate-500">圈选内容只会作为下一版修改指令提交，不会写入导出图片。</p><fieldset className="mt-4"><legend className="text-sm font-medium text-slate-700">问题标签（至少选择一项或填写说明）</legend><div className="mt-2 grid grid-cols-2 gap-2">{issueTags.map(([value, label]) => <label className="flex items-center gap-2 text-sm text-slate-700" key={value}><input type="checkbox" checked={selectedTags.includes(value)} onChange={() => setSelectedTags((tags) => tags.includes(value) ? tags.filter((tag) => tag !== value) : [...tags, value])} />{label}</label>)}</div></fieldset><label className="mt-4 block text-sm font-medium text-slate-700"><span className="mb-2 block">修改说明</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="说明需要调整的地方" /></label><div className="mt-4 grid grid-cols-2 gap-2"><button className="secondary-button justify-center" disabled={review.isPending || !canRequestChanges} onClick={() => submit("changes_requested")}>请求修改</button><button className="primary-button justify-center" disabled={review.isPending} onClick={() => submit("accept")}>通过</button></div></aside></div></Shell>;
}
