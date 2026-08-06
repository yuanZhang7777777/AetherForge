import { Link } from "react-router-dom";

import { ErrorPanel, PageHeading, Shell, statusText } from "../layout";
import { useWorkspaceSnapshot } from "../queries";
import { currentOutputs } from "../workspace";

export default function Production() {
  const workspace = useWorkspaceSnapshot();
  if (workspace.isLoading) return <Shell><PageHeading eyebrow="批量生产" title="正在读取生产队列…" /></Shell>;
  if (workspace.isError || !workspace.data) return <Shell><PageHeading eyebrow="批量生产" title="生产队列" /><ErrorPanel error={workspace.error ?? new Error("项目快照为空")} retry={() => void workspace.refetch()} /></Shell>;
  const rows = workspace.data.projects.map((project) => {
    const outputs = project.skus.flatMap((sku) => currentOutputs(sku.outputs));
    return {
      project,
      done: outputs.filter((output) => output.status === "completed").length,
      failed: outputs.filter((output) => output.status === "failed").length,
      active: outputs.filter((output) => output.status === "queued" || output.status === "running").length,
      total: outputs.length,
    };
  });
  return (
    <Shell>
      <PageHeading eyebrow="批量生产" title="生产队列" />
      <section className="surface overflow-hidden">
        <div className="overflow-x-auto">
          <table>
            <thead><tr><th>项目</th><th>完成</th><th>生成中</th><th>需处理</th><th>操作</th></tr></thead>
            <tbody>
              {rows.map(({ project, done, failed, active, total }) => (
                <tr key={project.id}>
                  <td><span className="font-medium text-slate-950">{project.name}</span><span className="ml-2 text-xs text-slate-400">{statusText(project.status)}</span></td>
                  <td>{done} / {total || "—"}</td>
                  <td>{active}</td>
                  <td>{failed}</td>
                  <td><Link className="text-sm font-semibold text-indigo-700" to={`/projects/${project.id}/results`}>查看结果</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Shell>
  );
}
