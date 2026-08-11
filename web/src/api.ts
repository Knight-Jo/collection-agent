import type { Artifact, Run, RunInput, SystemStatus, TaskDetail, TaskSummary } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error?.message ?? `请求失败 (${response.status})`);
  }
  return body as T;
}

export const api = {
  system: () => request<SystemStatus>("/api/system"),
  tasks: () => request<TaskSummary[]>("/api/tasks"),
  task: (id: string) => request<TaskDetail>(`/api/tasks/${id}`),
  artifact: (id: string, kind: Artifact["kind"]) =>
    request<Artifact>(`/api/tasks/${id}/artifacts/${kind}`),
  createRun: (input: RunInput) =>
    request<Run>("/api/runs", { method: "POST", body: JSON.stringify(input) }),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
};
