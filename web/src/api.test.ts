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
  await expect(api.conversation("task-1")).resolves.toEqual([]);
  await expect(api.sendMessage("task-1", "问题", "client-1")).resolves.toEqual([]);
  await expect(api.cancelMessage("message-1")).resolves.toEqual([]);
  await expect(api.retryMessage("message-1")).resolves.toEqual([]);
  await expect(api.confirmAction("action-1", "client-2")).resolves.toEqual([]);
  await expect(api.rejectAction("action-1")).resolves.toEqual([]);
  await expect(api.cancelAction("action-1")).resolves.toEqual([]);
  await expect(api.cancelResearchRun("research-run-1")).resolves.toEqual([]);
  await expect(api.conversations()).resolves.toEqual([]);
  await expect(api.createConversation()).resolves.toEqual([]);
  await expect(api.conversationById("conversation-1")).resolves.toEqual([]);
  await expect(api.sendConversationMessage("conversation-1", "问题", "client-3")).resolves.toEqual(
    [],
  );
  await expect(api.timeline("conversation-1", 4)).resolves.toEqual([]);
  await expect(api.stopResearchRun("research-run-1")).resolves.toEqual([]);
  await expect(api.researchRun("research-run-1")).resolves.toEqual([]);
  await expect(api.searchPlanVersion("plan-1")).resolves.toEqual([]);
  await expect(api.activeSearchPlan("research-run-1")).resolves.toEqual([]);
  await expect(api.reportVersion("report-1")).resolves.toEqual([]);
  await expect(api.createReportVersion("task-1")).resolves.toEqual([]);
  await expect(api.publishReportVersion("report-1")).resolves.toEqual([]);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/tasks/task-1/conversation/messages",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/report-versions/report-1/publish",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/conversations/conversation-1/messages",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/conversations/conversation-1/timeline?after_sequence=4",
    expect.anything(),
  );
});

it("surfaces the backend error message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ error: { message: "输入无效" } }),
    }),
  );

  await expect(api.system()).rejects.toThrow("输入无效");
});
