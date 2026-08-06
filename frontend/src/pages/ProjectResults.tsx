import { Link, useParams } from "react-router-dom";

import { ResultGrid } from "../components/ResultGrid";
import { ErrorPanel, PageHeading, Shell } from "../layout";
import { useProjectSnapshot } from "../queries";

export default function ProjectResults() {
  const { projectId } = useParams();
  const projectQuery = useProjectSnapshot(projectId);
  if (projectQuery.isLoading) return <Shell><PageHeading eyebrow="生产与结果" title="正在读取结果…" /></Shell>;
  if (projectQuery.isError || !projectQuery.data) return <Shell><PageHeading eyebrow="生产与结果" title="结果不可用" /><ErrorPanel error={projectQuery.error ?? new Error("项目快照为空")} retry={() => void projectQuery.refetch()} /></Shell>;
  const project = projectQuery.data;
  return (
    <Shell>
      <PageHeading
        eyebrow={project.name}
        title="生产与结果"
        action={<Link className="secondary-button" to={`/projects/${project.id}`}>返回项目工作区</Link>}
      />
      <ResultGrid project={project} />
    </Shell>
  );
}
