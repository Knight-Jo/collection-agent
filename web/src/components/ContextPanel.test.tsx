import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { ContextPanel } from "./ContextPanel";

vi.mock("../api", () => ({
  api: {
    researchRun: vi.fn(),
    searchPlanVersion: vi.fn(),
    activeSearchPlan: vi.fn(),
    reportVersion: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.searchPlanVersion).mockResolvedValue({
    id: "plan-version-4",
    task_id: "task-1",
    research_run_id: "run-1",
    sequence: 4,
    plan: { queries: ["先进封装 竞争格局"] },
    created_at: "2026-08-26T00:00:00Z",
  });
});

it("loads SearchPlan history by stable version ID", async () => {
  render(
    <ContextPanel
      selection={{ kind: "search_plan_version", id: "plan-version-4" }}
      onClose={() => undefined}
    />,
  );

  expect(await screen.findByText("Search Plan V4")).toBeVisible();
  expect(api.searchPlanVersion).toHaveBeenCalledWith("plan-version-4");
  expect(screen.getByText("先进封装 竞争格局", { exact: false })).toBeVisible();
});

it("shows citation detail and closes with Escape", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  render(
    <ContextPanel
      selection={{
        kind: "citation",
        value: {
          id: "citation-1",
          sequence: 1,
          citation_kind: "verified_evidence",
          title: "官方公告",
          source_url: "https://example.com/source",
          quote_text: "产品已经发布。",
          line_start: 3,
          line_end: 3,
        },
      }}
      onClose={onClose}
    />,
  );

  expect(screen.getByText("产品已经发布。")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});
