import { Link } from "react-router-dom";

import { ErrorPanel, PageHeading, Shell, statusText } from "../layout";
import { useWorkspaceSnapshot } from "../queries";
import { currentOutputs } from "../workspace";

export default function Dashboard() {
  const workspace = useWorkspaceSnapshot();
  if (workspace.isLoading) return <Shell><PageHeading eyebrow="运营工作台" title="正在读取工作台…" /></Shell>;
  if (workspace.isError || !workspace.data) return <Shell><PageHeading eyebrow="运营工作台" title="工作台" /><ErrorPanel error={workspace.error ?? new Error("项目快照为空")} retry={() => void workspace.refetch()} /></Shell>;
  const projects = workspace.data.projects;
  const outputs = projects.flatMap((project) => project.skus.flatMap((sku) => currentOutputs(sku.outputs)));
  const metrics = [
    ["输出图任务", outputs.length, "当前最新版本"],
    ["生成中", outputs.filter((item) => item.status === "running").length, "可进入队列查看"],
    ["已完成", outputs.filter((item) => item.status === "completed").length, "默认可选导出"],
    ["异常项", outputs.filter((item) => item.status === "failed").length, "只重做失败图"],
  ];
  return <Shell><PageHeading eyebrow="运营工作台" title="工作台" action={<Link className="primary-button" to="/projects/new">新建出图项目</Link>} /><section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{metrics.map(([label, value, note]) => <article className="surface p-5" key={label as string}><p className="text-sm text-slate-500">{label}</p><p className="mt-2 bg-gradient-to-br from-indigo-700 to-violet-600 bg-clip-text text-3xl font-bold tracking-tight text-transparent">{value}</p><p className="mt-2 text-xs text-slate-400">{note}</p></article>)}</section><section className="mt-9"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">最近项目</h2><span className="text-sm text-slate-500">按更新时间排序</span></div><div className="grid gap-4 lg:grid-cols-2">{projects.map((project) => { const current = project.skus.flatMap((sku) => currentOutputs(sku.outputs)); const done = current.filter((item) => item.status === "completed").length; return <Link to={`/projects/${project.id}`} className="surface group block p-5 transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lg hover:shadow-indigo-100" key={project.id}><div className="flex items-start justify-between gap-4"><div><h3 className="text-lg font-semibold group-hover:text-indigo-700">{project.name}</h3><p className="mt-1 text-sm text-slate-500">{project.platform} · {project.market} · {project.template}</p></div><span className={`status status-${project.status}`}>{statusText(project.status)}</span></div><div className="mt-6 flex items-end justify-between"><div><p className="text-2xl font-bold">{done}<span className="text-sm font-medium text-slate-400"> / {current.length || "—"}</span></p><p className="text-xs text-slate-400">已完成输出图</p></div><p className="text-xs text-slate-400">{new Date(project.updatedAt).toLocaleString()}</p></div></Link>; })}</div></section></Shell>;
}
