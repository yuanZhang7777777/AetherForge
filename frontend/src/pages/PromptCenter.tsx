import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createPromptNodeDraft, loadPromptNodes, publishPromptNode } from "../api";
import { platformLabel } from "../labels";
import { ErrorPanel, PageHeading, Shell } from "../layout";
import type { PromptNodeDraftInput, PromptNodeTemplate } from "../types";

const statusLabels = { draft: "草稿", published: "已发布", retired: "历史版本" };

export default function PromptCenter() {
  const queryClient = useQueryClient();
  const nodes = useQuery({ queryKey: ["prompt-nodes"], queryFn: loadPromptNodes });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const create = useMutation({ mutationFn: createPromptNodeDraft, onSuccess: async () => { setDraftOpen(false); await queryClient.invalidateQueries({ queryKey: ["prompt-nodes"] }); } });
  const publish = useMutation({ mutationFn: ({ nodeName, version }: { nodeName: string; version: string }) => publishPromptNode(nodeName, version), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompt-nodes"] }) });

  if (nodes.isLoading) return <Shell><PageHeading eyebrow="管理员" title="正在读取 Prompt 管理中心…" /></Shell>;
  if (nodes.isError) return <Shell><PageHeading eyebrow="管理员" title="Prompt 管理中心" /><ErrorPanel error={nodes.error} retry={() => void nodes.refetch()} /></Shell>;
  const templates = nodes.data?.nodes ?? [];
  const selected = templates.find((node) => node.id === selectedId) ?? templates[0];

  return <Shell>
    <PageHeading eyebrow="仅管理员可见" title="Prompt 管理中心" action={<button className="primary-button" type="button" onClick={() => setDraftOpen(true)}>新建草稿</button>} />
    {draftOpen && <DraftForm pending={create.isPending} error={create.error} onCancel={() => setDraftOpen(false)} onSave={(input) => create.mutate(input)} />}
    <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
      <section className="surface p-3" aria-label="Prompt 节点版本列表">{templates.map((node) => <button key={node.id} className={`review-item ${selected?.id === node.id ? "review-item-active" : ""}`} type="button" onClick={() => setSelectedId(node.id)}><span className="font-semibold">{node.node_name}</span><small>版本 {node.version} · {statusLabels[node.status]}</small></button>)}</section>
      {selected ? <PromptNodeDetail node={selected} pending={publish.isPending} error={publish.error} onPublish={() => publish.mutate({ nodeName: selected.node_name, version: selected.version })} /> : <section className="surface p-6 text-sm text-slate-500">还没有 Prompt 节点版本。</section>}
    </div>
  </Shell>;
}

function PromptNodeDetail({ node, pending, error, onPublish }: { node: PromptNodeTemplate; pending: boolean; error: unknown; onPublish: () => void }) {
  const metadata = [statusLabels[node.status], node.model, node.platform_scope ? platformLabel(node.platform_scope) : null].filter(Boolean).join(" · ");
  return <section className="surface min-w-0 p-6">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="section-label">运行时模板详情</p><h2 className="mt-1 text-xl font-semibold">{node.node_name} · 版本 {node.version}</h2><p className="mt-2 text-sm text-slate-500">{metadata}</p></div><button className="primary-button" type="button" disabled={pending || node.status === "published"} onClick={onPublish}>发布此版本</button></div>
    {error instanceof Error && <p className="mt-3 text-sm text-rose-700">{error.message}</p>}
    <Field title="系统 Prompt" value={node.instruction} />
    <Field title="用户消息模板" value={node.user_message_template || "（无）"} />
    <Field title="输出 Schema" value={JSON.stringify(node.output_schema, null, 2)} />
  </section>;
}

function Field({ title, value }: { title: string; value: string }) {
  return <section className="mt-5"><h3 className="text-sm font-semibold text-slate-700">{title}</h3><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">{value}</pre></section>;
}

function DraftForm({ pending, error, onSave, onCancel }: { pending: boolean; error: unknown; onSave: (input: PromptNodeDraftInput) => void; onCancel: () => void }) {
  const [input, setInput] = useState({ nodeName: "", version: "", instruction: "", userTemplate: "", schema: "{\n  \"type\": \"object\"\n}" });
  const [schemaError, setSchemaError] = useState("");
  const submit = () => {
    try {
      const outputSchema = JSON.parse(input.schema) as unknown;
      setSchemaError("");
      onSave({ node_name: input.nodeName.trim(), version: input.version.trim(), instruction: input.instruction, user_message_template: input.userTemplate || undefined, output_schema: outputSchema });
    } catch {
      setSchemaError("输出 Schema 必须是有效 JSON");
    }
  };
  return <section className="surface mb-5 p-5"><h2 className="text-lg font-semibold">新建 Prompt 草稿</h2><div className="mt-4 grid gap-4 md:grid-cols-2"><label className="text-sm font-medium">节点名称<input aria-label="节点名称" className="mt-2" value={input.nodeName} onChange={(event) => setInput({ ...input, nodeName: event.target.value })} /></label><label className="text-sm font-medium">版本<input aria-label="版本" className="mt-2" value={input.version} onChange={(event) => setInput({ ...input, version: event.target.value })} /></label><label className="text-sm font-medium md:col-span-2">系统 Prompt<textarea aria-label="系统 Prompt" className="mt-2 min-h-40" value={input.instruction} onChange={(event) => setInput({ ...input, instruction: event.target.value })} /></label><label className="text-sm font-medium md:col-span-2">用户消息模板<textarea aria-label="用户消息模板" className="mt-2" value={input.userTemplate} onChange={(event) => setInput({ ...input, userTemplate: event.target.value })} /></label><label className="text-sm font-medium md:col-span-2">输出 Schema<textarea aria-label="输出 Schema" className="mt-2 min-h-40 font-mono" value={input.schema} onChange={(event) => setInput({ ...input, schema: event.target.value })} /></label></div>{(schemaError || error instanceof Error) && <p className="mt-3 text-sm text-rose-700">{schemaError || (error as Error).message}</p>}<div className="mt-4 flex gap-2"><button className="primary-button" type="button" disabled={pending || !input.nodeName.trim() || !input.version.trim() || !input.instruction.trim()} onClick={submit}>保存草稿</button><button className="secondary-button" type="button" onClick={onCancel}>取消</button></div></section>;
}
