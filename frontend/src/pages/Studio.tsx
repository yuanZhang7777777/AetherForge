import { Navigate, useParams } from "react-router-dom";

export default function Studio() {
  const { projectId } = useParams();
  return <Navigate replace to={projectId ? `/projects/${projectId}` : "/"} />;
}
