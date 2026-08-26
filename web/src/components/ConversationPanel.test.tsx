import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { ConversationPanel } from "./ConversationPanel";

vi.mock("../api", () => ({
  api: {
    conversationById: vi.fn(),
    timeline: vi.fn().mockResolvedValue([]),
    sendConversationMessage: vi.fn().mockResolvedValue({}),
    stopResearchRun: vi.fn().mockResolvedValue({}),
    cancelResearchRun: vi.fn().mockResolvedValue({}),
    confirmAction: vi.fn().mockResolvedValue({}),
    rejectAction: vi.fn().mockResolvedValue({}),
    retryMessage: vi.fn().mockResolvedValue({}),
    createReportVersion: vi.fn().mockResolvedValue({}),
    publishReportVersion: vi.fn().mockResolvedValue({}),
  },
}));

const projection = {
  conversation: {
    id: "conversation-1",
    task_id: "task-1",
    status: "active" as const,
    title: "先进封装产业",
    active_epoch_id: "epoch-1",
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
  },
  epoch: { id: "epoch-1", summary: "" },
  messages: [
    {
      id: "message-1",
      role: "assistant" as const,
      content: "目前可以确认竞争格局。",
      status: "completed" as const,
      citations: [],
    },
  ],
  processing_attempts: [],
  actions: [],
  runs: [
    {
      id: "run-17",
      task_id: "task-1",
      active_search_plan_version_id: "plan-4",
      status: "running" as const,
      phase: "collecting" as const,
      error: null,
    },
  ],
  reports: [],
  committed_state_version: 7,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.conversationById).mockResolvedValue(projection);
});

it("shows committed state separately from live Run progress", async () => {
  render(<ConversationPanel conversationId="conversation-1" />);

  expect(await screen.findByText("调研进行中")).toBeVisible();
  expect(screen.getByText("已提交：研究状态 v7")).toBeVisible();
  expect(screen.getByText("当前运行：正在收集材料")).toBeVisible();
});

it("stops the concrete running Run", async () => {
  const user = userEvent.setup();
  render(<ConversationPanel conversationId="conversation-1" />);

  await user.click(await screen.findByRole("button", { name: "停止当前调研" }));

  expect(api.stopResearchRun).toHaveBeenCalledWith("run-17");
});

it("sends messages through the selected Conversation", async () => {
  const user = userEvent.setup();
  render(<ConversationPanel conversationId="conversation-1" />);

  await user.type(await screen.findByLabelText("输入消息"), "继续调查日本企业");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(api.sendConversationMessage).toHaveBeenCalledWith(
    "conversation-1",
    "继续调查日本企业",
    expect.any(String),
  );
});

it("offers retry when processing a user message failed", async () => {
  const user = userEvent.setup();
  vi.mocked(api.conversationById).mockResolvedValue({
    ...projection,
    messages: [
      {
        id: "message-user-1",
        role: "user",
        content: "调研先进封装",
        status: "accepted",
        citations: [],
      },
    ],
    processing_attempts: [
      {
        id: "attempt-1",
        user_message_id: "message-user-1",
        status: "failed",
        error_detail: "模型暂时不可用",
      },
    ],
  });
  render(<ConversationPanel conversationId="conversation-1" />);

  await user.click(await screen.findByRole("button", { name: "重试处理" }));

  expect(api.retryMessage).toHaveBeenCalledWith("message-user-1");
});

it("creates and publishes report drafts explicitly", async () => {
  const user = userEvent.setup();
  vi.mocked(api.conversationById).mockResolvedValue({
    ...projection,
    runs: [],
    reports: [
      {
        id: "report-2",
        version: 2,
        status: "draft",
        content_path: "output/report-2.md",
        based_on_checkpoint_id: "checkpoint-7",
        based_on_committed_state_version: 7,
        created_at: "2026-08-26T00:00:00Z",
      },
    ],
  });
  render(<ConversationPanel conversationId="conversation-1" />);

  await user.click(await screen.findByRole("button", { name: "生成报告草稿" }));
  await user.click(screen.getByRole("button", { name: "发布 V2" }));

  expect(api.createReportVersion).toHaveBeenCalledWith("task-1");
  expect(api.publishReportVersion).toHaveBeenCalledWith("report-2");
});
