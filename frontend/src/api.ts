import { developmentWorkspace } from "./mock-data";
import type { ClusterUpdateInput, ClusterUpdateResult, CurrentUser, ImportMode, PreflightResult, ProductConfiguration, Project, ProjectInput, ProjectProgress, PromptNodeDraftInput, PromptNodeTemplate, ReviewInput, RevisionInput, SkuImportResult, WorkspaceSnapshot } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public authRequired = false) {
    super(message);
    this.name = "ApiError";
  }
}

function demoMode() {
  return import.meta.env.VITE_DEMO_MODE === "true";
}

type JsonResponse = {
  ok: boolean;
  status: number;
  redirected?: boolean;
  url?: string;
  headers?: { get(name: string): string | null };
  json: () => Promise<unknown>;
};

function isAuthenticationUrl(url: string | undefined) {
  if (!url) return false;
  try {
    const path = new URL(url, window.location.origin).pathname.toLowerCase();
    return /(?:^|\/)(?:login|password)(?:\/|$)/.test(path);
  } catch {
    return false;
  }
}

function isLoginResponse(response: JsonResponse) {
  return Boolean(response.redirected) || isAuthenticationUrl(response.url);
}

function isLogoutRedirect(response: JsonResponse) {
  if (!response.redirected || !response.url) return false;
  try {
    return new URL(response.url, window.location.origin).pathname === "/login/";
  } catch {
    return false;
  }
}

async function errorFor(response: JsonResponse) {
  if (isLoginResponse(response)) return new ApiError(401, "登录已失效或需修改密码", true);
  let message = `请求失败（${response.status}）`;
  try {
    const body = await response.json() as { error?: string; message?: string };
    message = body.error ?? body.message ?? message;
  } catch {
    // Keep the status-based message when the server did not return JSON.
  }
  return new ApiError(response.status, message, response.status === 401);
}

async function jsonFor<T>(response: JsonResponse): Promise<T> {
  if (!response.ok || isLoginResponse(response)) throw await errorFor(response);
  return response.json() as Promise<T>;
}

async function csrfToken() {
  const response = await fetch("/api/csrf/", { credentials: "same-origin" });
  const payload = await jsonFor<{ csrf_token?: string }>(response);
  if (!payload.csrf_token) throw new ApiError(500, "CSRF 初始化响应无效");
  return payload.csrf_token;
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.method && init.method !== "GET") {
    headers.set("Content-Type", "application/json");
    headers.set("X-CSRFToken", await csrfToken());
  }
  const response = await fetch(url, { ...init, headers, credentials: "same-origin" });
  return jsonFor<T>(response);
}

export async function logoutUser(): Promise<void> {
  let token = "";
  try {
    token = await csrfToken();
  } catch (error) {
    if (error instanceof ApiError && error.authRequired) return;
    throw error;
  }
  const response = await fetch("/logout/", {
    method: "POST",
    headers: new Headers({ "X-CSRFToken": token }),
    credentials: "same-origin",
  });
  if (isLoginResponse(response) || response.status === 401 || response.status === 403) return;
  if (!response.ok || !isLogoutRedirect(response)) throw await errorFor(response);
}

export async function loadWorkspace(): Promise<WorkspaceSnapshot> {
  try {
    return await jsonRequest<WorkspaceSnapshot>("/api/workspace/snapshot/");
  } catch (error) {
    if (demoMode()) return developmentWorkspace;
    throw error;
  }
}

export function loadCurrentUser(): Promise<CurrentUser> {
  return jsonRequest<CurrentUser>("/api/current-user/");
}

export function loadProject(projectId: string) {
  return jsonRequest<Project>(`/api/projects/${projectId}/snapshot/`);
}

export function loadProjectProgress(projectId: string) {
  return jsonRequest<ProjectProgress>(`/api/projects/${projectId}/progress/`);
}

export interface UploadResult {
  asset_count: number;
  imported: { filename: string; asset_id: string; cluster_id: string | null }[];
  rejected: { filename: string; code: string; message: string }[];
}

export function uploadPath(file: File) {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

export async function createProject(input: ProjectInput): Promise<Project> {
  const payload = { name: input.name.trim() };
  try {
    return await jsonRequest<Project>("/api/projects/", { method: "POST", body: JSON.stringify(payload) });
  } catch (error) {
    if (!demoMode()) throw error;
    return {
      id: `demo-project-${crypto.randomUUID()}`,
      ...payload,
      platform: "",
      market: "",
      template: "",
      size: "1:1",
      resolution: "1k",
      status: "draft",
      assets: [],
      skus: [],
      updatedAt: new Date().toISOString(),
    };
  }
}

export function updateProjectSettings(projectId: string, input: ProductConfiguration) {
  return jsonRequest<Project>(`/api/projects/${projectId}/settings/`, {
    method: "PATCH",
    body: JSON.stringify({
      platform: input.platform,
      market: input.market.trim().toUpperCase(),
      size: input.size,
      resolution: input.resolution,
      global_prompt: input.globalPrompt,
      ai_recognition_enabled: input.aiRecognitionEnabled ?? false,
    }),
  });
}

export function prepareProject(projectId: string, clusterIds: string[]) {
  return jsonRequest<{ items: { cluster_id: string; status: string; stage?: string; code?: string; message?: string }[] }>(`/api/projects/${projectId}/prepare/`, {
    method: "POST",
    body: JSON.stringify({ cluster_ids: clusterIds }),
  });
}

export async function uploadAssets(projectId: string, files: File[], mode: ImportMode = "organize") {
  const sorted = [...files].sort((left, right) => {
    const leftTxt = uploadPath(left).toLowerCase().endsWith(".txt");
    const rightTxt = uploadPath(right).toLowerCase().endsWith(".txt");
    return Number(rightTxt) - Number(leftTxt) || uploadPath(left).localeCompare(uploadPath(right));
  });
  const txtCount = sorted.filter((file) => uploadPath(file).toLowerCase().endsWith(".txt")).length;
  if (txtCount > 20 || sorted.length - txtCount > 100) {
    throw new ApiError(400, "单次最多上传 100 张图片和 20 个 TXT");
  }

  const token = await csrfToken();
  const result: UploadResult = { asset_count: 0, imported: [], rejected: [] };
  for (let index = 0; index < sorted.length; index += 50) {
    const body = new FormData();
    body.append("mode", mode);
    sorted.slice(index, index + 50).forEach((file) => {
      const relativePath = uploadPath(file);
      body.append("files", file, relativePath);
      body.append("relative_paths", relativePath);
    });
    const headers = new Headers({ "X-CSRFToken": token });
    let chunk: Partial<UploadResult>;
    try {
      const response = await fetch(`/api/projects/${projectId}/assets/`, {
        method: "POST",
        body,
        headers,
        credentials: "same-origin",
      });
      chunk = await jsonFor<Partial<UploadResult>>(response);
    } catch (error) {
      if (result.imported.length === 0) throw error;
      result.rejected.push(...sorted.slice(index).map((file) => ({
        filename: uploadPath(file),
        code: "upload_interrupted",
        message: "上传中断，请重试剩余文件",
      })));
      break;
    }
    result.asset_count += chunk.asset_count ?? 0;
    result.imported.push(...(chunk.imported ?? []));
    result.rejected.push(...(chunk.rejected ?? []));
  }
  return result;
}

export function importSkus(projectId: string, skus: string[], mode: ImportMode) {
  return jsonRequest<SkuImportResult>(`/api/projects/${projectId}/sku-import/`, {
    method: "POST",
    body: JSON.stringify({ skus, mode }),
  });
}

export function updateCluster(clusterId: string, expectedVersion: number, payload: ClusterUpdateInput) {
  return jsonRequest<ClusterUpdateResult>(`/api/clusters/${clusterId}/`, {
    method: "POST",
    body: JSON.stringify({ expected_version: expectedVersion, ...payload }),
  });
}

export function deleteCluster(clusterId: string) {
  return jsonRequest<{ status: "deleted" | "archived" }>(`/api/clusters/${clusterId}/`, {
    method: "DELETE",
  });
}

export function deleteAsset(assetId: string) {
  return jsonRequest<{ status: "deleted" | "archived" }>(`/api/assets/${assetId}/`, {
    method: "DELETE",
  });
}

export function mergeAsset(clusterId: string, assetId: string, expectedVersion: number) {
  return jsonRequest(`/api/clusters/${clusterId}/merge/`, {
    method: "POST",
    body: JSON.stringify({ asset_id: assetId, expected_version: expectedVersion }),
  });
}

export function splitAsset(assetId: string) {
  return jsonRequest(`/api/assets/${assetId}/split/`, { method: "POST", body: "{}" });
}

export function loadPromptNodes() {
  return jsonRequest<{ nodes: PromptNodeTemplate[] }>("/api/admin/prompt-nodes/");
}

export function createPromptNodeDraft(input: PromptNodeDraftInput) {
  return jsonRequest<PromptNodeTemplate>("/api/admin/prompt-nodes/", { method: "POST", body: JSON.stringify(input) });
}

export function publishPromptNode(nodeName: string, version: string) {
  return jsonRequest<PromptNodeTemplate>("/api/admin/prompt-nodes/publish/", {
    method: "POST",
    body: JSON.stringify({ node_name: nodeName, version }),
  });
}

export function confirmProject(projectId: string) {
  return jsonRequest(`/api/projects/${projectId}/confirm/`, { method: "POST", body: "{}" });
}

export function generateProject(projectId: string, input: { clusterIds: string[]; slotOrders: number[] }) {
  return jsonRequest(`/api/projects/${projectId}/generate/`, {
    method: "POST",
    body: JSON.stringify({ cluster_ids: input.clusterIds, slot_orders: input.slotOrders }),
  });
}

export function pauseProject(projectId: string, input: { clusterIds?: string[]; generationIds?: string[] }) {
  const body: { cluster_ids?: string[]; generation_ids?: string[] } = {};
  if (input.clusterIds?.length) body.cluster_ids = input.clusterIds;
  if (input.generationIds?.length) body.generation_ids = input.generationIds;
  return jsonRequest(`/api/projects/${projectId}/pause/`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function preflightProject(projectId: string): Promise<PreflightResult> {
  const result = await jsonRequest<PreflightResult>(`/api/projects/${projectId}/preflight/`, { method: "POST", body: "{}" });
  return {
    cluster_count: result.cluster_count,
    slot_count: result.slot_count,
    generation_count: result.generation_count,
    blocking_errors: result.blocking_errors,
  };
}

export function retryGeneration(generationId: string) {
  return jsonRequest(`/api/generations/${generationId}/retry/`, { method: "POST", body: "{}" });
}

export function regenerateGeneration(generationId: string) {
  return jsonRequest(`/api/generations/${generationId}/regenerate/`, { method: "POST", body: "{}" });
}

export function submitReview(generationId: string, input: ReviewInput) {
  return jsonRequest(`/api/generations/${generationId}/review/`, { method: "POST", body: JSON.stringify(input) });
}

export function reviseGeneration(generationId: string, input: RevisionInput) {
  return jsonRequest(`/api/generations/${generationId}/revise/`, { method: "POST", body: JSON.stringify(input) });
}

export async function exportProject(projectId: string, generationIds: string[] = []) {
  const headers = new Headers({ "Content-Type": "application/json", "X-CSRFToken": await csrfToken() });
  const response = await fetch(`/api/projects/${projectId}/export/`, {
    method: "POST",
    body: JSON.stringify({ generation_ids: generationIds }),
    headers,
    credentials: "same-origin",
  });
  if (!response.ok || isLoginResponse(response)) throw await errorFor(response);
  return response.blob();
}
