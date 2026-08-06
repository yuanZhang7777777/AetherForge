import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { loadProject, loadProjectProgress, loadWorkspace } from "./api";
import type { Project } from "./types";
import { mergeProjectProgress, progressPollInterval, projectHasActiveWork, workspacePollInterval } from "./workspace";

function usePageHidden() {
  const [hidden, setHidden] = useState(document.hidden);
  useEffect(() => {
    const update = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return hidden;
}

export function useWorkspaceSnapshot() {
  const hidden = usePageHidden();
  return useQuery({
    queryKey: ["workspace"],
    queryFn: loadWorkspace,
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    refetchOnMount: false,
    refetchInterval: (query) => workspacePollInterval(
      query.state.data?.projects.some(projectHasActiveWork) ?? false,
      hidden,
    ),
  });
}

export function useProjectSnapshot(projectId: string | undefined) {
  const hidden = usePageHidden();
  const queryClient = useQueryClient();
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => loadProject(projectId!),
    enabled: Boolean(projectId),
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    refetchOnMount: false,
    refetchInterval: false,
  });
  useQuery({
    queryKey: ["project-progress", projectId],
    queryFn: async () => {
      const progress = await loadProjectProgress(projectId!);
      queryClient.setQueryData<Project>(["project", projectId], (current) => (
        current ? mergeProjectProgress(current, progress) : current
      ));
      if (!projectHasActiveWork({ ...projectQuery.data!, status: progress.status, skus: progress.skus })) {
        void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      }
      return progress;
    },
    enabled: Boolean(projectId && projectQuery.data),
    refetchInterval: (query) => progressPollInterval(
      query.state.data ? projectHasActiveWork(query.state.data) : projectQuery.data ? projectHasActiveWork(projectQuery.data) : false,
      hidden,
    ),
  });
  return projectQuery;
}
