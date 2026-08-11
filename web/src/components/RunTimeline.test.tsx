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
