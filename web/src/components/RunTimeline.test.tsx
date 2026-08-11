import { render, screen } from "@testing-library/react";
import { RunTimeline } from "./RunTimeline";

it("translates tool events into plain-language progress", () => {
  render(
    <RunTimeline
      events={[
        {
          id: 1,
          type: "tool.started",
          timestamp: "2026-08-11T09:00:00Z",
          data: { tool_name: "web_search" },
        },
        {
          id: 2,
          type: "tool.completed",
          timestamp: "2026-08-11T09:00:03Z",
          data: { tool_name: "evidence_audit" },
        },
      ]}
    />,
  );

  expect(screen.getByText("正在检索公开来源")).toBeInTheDocument();
  expect(screen.getByText("语义审核已完成")).toBeInTheDocument();
});

it("shows crawl progress and resources with their completed state", () => {
  render(
    <RunTimeline
      events={[
        { id: 1, type: "crawl.started", timestamp: "2026-08-11T09:00:00Z", data: {} },
        { id: 2, type: "crawl.progress", timestamp: "2026-08-11T09:00:01Z", data: { counts: { queued: 2, complete: 1, reused: 0 } } },
        { id: 3, type: "crawl.resource", timestamp: "2026-08-11T09:00:02Z", data: { resource: { canonical_url: "https://example.com/a" } } },
        { id: 4, type: "crawl.completed", timestamp: "2026-08-11T09:00:03Z", data: {} },
      ]}
    />,
  );

  expect(screen.getByText("正在开始深度抓取")).toBeInTheDocument();
  expect(screen.getByText("深度抓取进度：已完成 1，待处理 2")).toBeInTheDocument();
  expect(screen.getByText("已发现抓取资源")).toBeInTheDocument();
  expect(screen.getByText("深度抓取已完成")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem").map((item) => item.dataset.state)).toEqual([
    "running", "running", "completed", "completed",
  ]);
});

it("does not show failed or skipped crawl resources as completed", () => {
  render(
    <RunTimeline
      events={[
        { id: 1, type: "crawl.resource", timestamp: "2026-08-11T09:00:00Z", data: { resource: { status: "failed" } } },
        { id: 2, type: "crawl.resource", timestamp: "2026-08-11T09:00:01Z", data: { resource: { status: "skipped_robots" } } },
      ]}
    />,
  );

  expect(screen.getByText("抓取资源失败")).toBeInTheDocument();
  expect(screen.getByText("已跳过抓取资源")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem").map((item) => item.dataset.state)).toEqual(["failed", "skipped"]);
});
