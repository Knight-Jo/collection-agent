import { render, screen } from "@testing-library/react";
import { RunTimeline } from "./RunTimeline";

it("renders run and crawl lifecycle events", () => {
  render(
    <RunTimeline
      events={[
        { id: 1, type: "run.started", timestamp: "2026-08-11T09:00:00Z", data: {} },
        { id: 2, type: "task.updated", timestamp: "2026-08-11T09:00:03Z", data: { task_id: "task-1", stage: "collect" } },
      ]}
    />,
  );

  expect(screen.getByText("研究任务已启动")).toBeInTheDocument();
  expect(screen.getByText("任务状态已更新")).toBeInTheDocument();
});

it("filters trajectory events out of the progress timeline", () => {
  render(
    <RunTimeline
      events={[
        { id: 1, type: "run.started", timestamp: "2026-08-11T09:00:00Z", data: {} },
        { id: 2, type: "trajectory.decision", timestamp: "2026-08-11T09:00:01Z", data: { event_type: "decision" } },
      ]}
    />,
  );

  expect(screen.getByText("研究任务已启动")).toBeInTheDocument();
  expect(screen.queryByText("研究进度已更新")).not.toBeInTheDocument();
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
