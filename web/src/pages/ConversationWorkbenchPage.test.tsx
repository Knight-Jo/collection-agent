import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api";

vi.mock("../api", () => ({
  api: {
    conversations: vi.fn().mockResolvedValue([]),
    createConversation: vi.fn().mockResolvedValue({
      id: "conversation-1",
      task_id: null,
      status: "intake",
      title: "新对话",
      updated_at: "2026-08-26T00:00:00Z",
    }),
    conversationById: vi.fn(),
    archiveConversation: vi.fn(),
    restoreConversation: vi.fn(),
  },
}));

beforeEach(() => vi.clearAllMocks());

it("uses conversations as the primary workbench entry", async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  expect((await screen.findAllByRole("button", { name: "新建对话" })).length).toBeGreaterThan(0);
  expect(screen.queryByLabelText("研究主题")).not.toBeInTheDocument();
  expect(screen.getByText("从一个问题开始调研")).toBeVisible();
});

it("shows active research progress in the conversation sidebar", async () => {
  vi.mocked(api.conversations).mockResolvedValue([
    {
      id: "conversation-running",
      task_id: "task-running",
      status: "active",
      title: "先进封装产业",
      active_epoch_id: "epoch-running",
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:00Z",
      run_status: "running",
      run_phase: "collecting",
    },
  ]);

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  expect(await screen.findByText("正在收集材料")).toBeVisible();
});

it("updates sidebar progress after intake starts the selected research", async () => {
  const intake = {
    id: "conversation-selected",
    task_id: null,
    status: "intake" as const,
    title: "新对话",
    active_epoch_id: "epoch-selected",
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
  };
  vi.mocked(api.conversations).mockResolvedValue([intake]);
  vi.mocked(api.conversationById).mockResolvedValue({
    conversation: {
      ...intake,
      task_id: "task-selected",
      status: "active",
      title: "先进封装产业",
    },
    epoch: { id: "epoch-selected", summary: "" },
    messages: [],
    processing_attempts: [],
    actions: [],
    runs: [
      {
        id: "run-selected",
        task_id: "task-selected",
        active_search_plan_version_id: "plan-selected",
        status: "running",
        phase: "assessing",
        error: null,
      },
    ],
    reports: [],
    committed_state_version: 0,
    report_ready: false,
  });

  render(
    <MemoryRouter initialEntries={["/conversations/conversation-selected"]}>
      <App />
    </MemoryRouter>,
  );

  expect(await within(screen.getByLabelText("历史会话")).findByText("正在评估证据")).toBeVisible();
});

it("keeps the latest selected conversation when an older request finishes late", async () => {
  const user = userEvent.setup();
  const conversations = [
    {
      id: "conversation-1",
      task_id: "task-1",
      status: "active" as const,
      title: "会话一",
      active_epoch_id: "epoch-1",
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:00Z",
    },
    {
      id: "conversation-2",
      task_id: "task-2",
      status: "active" as const,
      title: "会话二",
      active_epoch_id: "epoch-2",
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:00Z",
    },
  ];
  const resolvers = new Map<string, (value: unknown) => void>();
  vi.mocked(api.conversations).mockResolvedValue(conversations);
  vi.mocked(api.conversationById).mockImplementation(
    (id) =>
      new Promise((resolve) => {
        resolvers.set(id, resolve);
      }) as never,
  );
  const projection = (conversation: (typeof conversations)[number]) => ({
    conversation,
    epoch: { id: conversation.active_epoch_id ?? "", summary: "" },
    messages: [],
    processing_attempts: [],
    actions: [],
    runs: [],
    reports: [],
    committed_state_version: 0,
    report_ready: false,
  });
  render(
    <MemoryRouter initialEntries={["/conversations/conversation-1"]}>
      <App />
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: "会话二调研会话" }));
  await act(async () => resolvers.get("conversation-2")?.(projection(conversations[1])));
  expect(await screen.findByRole("heading", { name: "会话二" })).toBeVisible();

  await act(async () => resolvers.get("conversation-1")?.(projection(conversations[0])));
  expect(screen.getByRole("heading", { name: "会话二" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "会话一" })).not.toBeInTheDocument();
});

it("archives the selected conversation after confirmation", async () => {
  const user = userEvent.setup();
  const conversation = {
    id: "conversation-1",
    task_id: null,
    status: "intake" as const,
    title: "待清理会话",
    active_epoch_id: "epoch-1",
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
  };
  vi.mocked(api.conversations).mockResolvedValueOnce([conversation]).mockResolvedValueOnce([]);
  vi.mocked(api.conversationById).mockResolvedValue({
    conversation,
    epoch: { id: "epoch-1", summary: "" },
    messages: [],
    processing_attempts: [],
    actions: [],
    runs: [],
    reports: [],
    committed_state_version: 0,
    report_ready: false,
  });
  vi.mocked(api.archiveConversation).mockResolvedValue({
    ...conversation,
    status: "archived",
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <MemoryRouter initialEntries={["/conversations/conversation-1"]}>
      <App />
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: "删除会话 待清理会话" }));

  expect(api.archiveConversation).toHaveBeenCalledWith("conversation-1");
  expect(await screen.findByText("从一个问题开始调研")).toBeVisible();
  expect(screen.queryByText("待清理会话")).not.toBeInTheDocument();
});

it("restores an archived conversation", async () => {
  const user = userEvent.setup();
  const conversation = {
    id: "conversation-1",
    task_id: null,
    status: "archived" as const,
    title: "已归档会话",
    active_epoch_id: "epoch-1",
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
  };
  vi.mocked(api.conversations).mockImplementation(async (archived = false) =>
    archived ? [conversation] : [],
  );
  vi.mocked(api.restoreConversation).mockResolvedValue({
    ...conversation,
    status: "intake",
  });
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: "查看已归档" }));
  await user.click(await screen.findByRole("button", { name: "恢复会话 已归档会话" }));

  expect(api.restoreConversation).toHaveBeenCalledWith("conversation-1");
  expect(await screen.findByText("暂无已归档会话")).toBeVisible();
});
