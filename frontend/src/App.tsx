import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const ProjectNew = lazy(() => import("./pages/ProjectNew"));
const ProjectGrouping = lazy(() => import("./pages/ProjectGrouping"));
const ProjectResults = lazy(() => import("./pages/ProjectResults"));
const Production = lazy(() => import("./pages/Production"));
const PromptCenter = lazy(() => import("./pages/PromptCenter"));

export default function App() {
  return <Suspense fallback={<main className="grid min-h-screen place-items-center text-sm text-slate-500">正在加载工作台…</main>}><Routes><Route path="/" element={<Dashboard />} /><Route path="/projects/new" element={<ProjectNew />} /><Route path="/projects/:projectId" element={<ProjectGrouping />} /><Route path="/projects/:projectId/results" element={<ProjectResults />} /><Route path="/production" element={<Production />} /><Route path="/admin/prompt-center" element={<PromptCenter />} /></Routes></Suspense>;
}
