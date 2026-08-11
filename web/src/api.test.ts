import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("returns API responses for every workbench endpoint", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
  vi.stubGlobal("fetch", fetchMock);

  await expect(api.system()).resolves.toEqual([]);
  await expect(api.tasks()).resolves.toEqual([]);
  await expect(api.task("task-1")).resolves.toEqual([]);
  await expect(api.artifact("task-1", "assessment")).resolves.toEqual([]);
  await expect(api.createRun({ topic: "topic", questions: ["one", "two"], deep_crawl: false, criteria: { min_independent_sources: 2, min_high_quality_sources: 1, recency_days: 90, require_recency: false } })).resolves.toEqual([]);
  await expect(api.run("run-1")).resolves.toEqual([]);
  await expect(api.cancelRun("run-1")).resolves.toEqual([]);
  expect(fetchMock).toHaveBeenCalledWith("/api/runs", expect.objectContaining({ method: "POST" }));
  expect(fetchMock).toHaveBeenCalledWith("/api/runs/run-1/cancel", expect.objectContaining({ method: "POST" }));
});

it("surfaces the backend error message", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ error: { message: "输入无效" } }) }));

  await expect(api.system()).rejects.toThrow("输入无效");
});
