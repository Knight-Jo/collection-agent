import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "../App";

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
