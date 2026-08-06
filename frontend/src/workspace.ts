import type { Project, ProjectProgress } from "./types";

export interface AttemptedOutput {
  id: string;
  slot: string;
  slotId: string;
  slotOrder: number;
  attempt: number;
}

export function currentOutputs<T extends AttemptedOutput>(outputs: T[]): T[] {
  const latest = new Map<string, T>();
  outputs.forEach((output) => {
    const current = latest.get(output.slotId);
    if (!current || output.attempt > current.attempt) latest.set(output.slotId, output);
  });
  return Array.from(latest.values()).sort((left, right) => left.slotOrder - right.slotOrder);
}

export function progressPollInterval(active: boolean, hidden: boolean): number | false {
  if (!active) return false;
  return hidden ? 15_000 : 3_000;
}

export function workspacePollInterval(active: boolean, hidden: boolean): number | false {
  if (!active) return false;
  return hidden ? 60_000 : 15_000;
}

export function projectHasActiveWork(project: { status: string; skus: Array<{ preparationStatus?: string; preparation?: { status?: string }; generationProgress?: { status?: string; active?: number; total?: number }; outputs: Array<{ status: string }> }> }) {
  return project.status === "queued" || project.status === "running" || project.skus.some((sku) =>
    sku.preparationStatus === "pending"
    || sku.preparationStatus === "preparing"
    || sku.preparation?.status === "pending"
    || sku.preparation?.status === "preparing"
    || (sku.generationProgress?.active ?? 0) > 0
    || sku.generationProgress?.status === "queued"
    || sku.generationProgress?.status === "running"
    || sku.outputs.some((output) => output.status === "queued" || output.status === "running"),
  );
}

export function mergeProjectProgress(project: Project, progress: ProjectProgress): Project {
  const byId = new Map(progress.skus.map((sku) => [sku.id, sku]));
  return {
    ...project,
    status: progress.status,
    updatedAt: progress.updatedAt,
    skus: project.skus.map((sku) => {
      const next = byId.get(sku.id);
      return next ? {
        ...sku,
        preparationStatus: next.preparationStatus ?? sku.preparationStatus,
        preparation: next.preparation ?? sku.preparation,
        generationProgress: next.generationProgress ?? sku.generationProgress,
        prompts: next.prompts ?? sku.prompts,
        outputs: next.outputs ?? sku.outputs,
      } : sku;
    }),
  };
}
