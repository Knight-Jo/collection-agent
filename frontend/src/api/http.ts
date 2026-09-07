const BASE = "/api";

export async function errorMessage(response: Response): Promise<string> {
  let detail: unknown;
  try {
    const data = (await response.json()) as Record<string, unknown>;
    detail = data.detail;
  } catch {
    detail = undefined;
  }
  const message = typeof detail === "string" ? detail : undefined;
  return message || `${response.status} ${response.statusText}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as T;
}

export function httpGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function httpPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function httpPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
