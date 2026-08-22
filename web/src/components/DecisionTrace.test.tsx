import { render, screen } from "@testing-library/react";
import { DecisionTrace } from "./DecisionTrace";

const envelope = (event_type: string, step_id: number, payload: Record<string, unknown>, sequence: number) => ({
  schema_version: "1.0",
  run_id: "run-1",
  task_id: "task-1",
  event_id: `evt-${sequence}`,
  sequence,
  parent_event_id: null,
  timestamp: "2026-08-11T09:00:00Z",
  layer: "business",
  event_type,
  origin: "model",
  question_id: null,
  step_id,
  payload,
});

it("renders decisions grouped by step with reasons and state changes", () => {
  render(
    <DecisionTrace
      events={[
        { id: 1, type: "trajectory.decision", timestamp: "2026-08-11T09:00:00Z", data: envelope("decision", 1, { decision: "web_search", reason_codes: ["LOW_COVERAGE"], reason_source: "derived", reason_summary: "关键问题覆盖不足", state_snapshot: { gap_score: 3 } }, 1) },
        { id: 2, type: "trajectory.action", timestamp: "2026-08-11T09:00:01Z", data: envelope("action", 1, { action_id: "act-1", tool: "web_search" }, 2) },
        { id: 3, type: "trajectory.state_updated", timestamp: "2026-08-11T09:00:02Z", data: envelope("state_updated", 1, { state_scope: "task", delta: { search_attempts: { before: 0, after: 1 } } }, 3) },
      ]}
    />,
  );

  expect(screen.getByText(/决策：web_search/)).toBeInTheDocument();
  expect(screen.getByText("覆盖不足")).toBeInTheDocument();
  expect(screen.getByText("关键问题覆盖不足")).toBeInTheDocument();
  expect(screen.getByText(/行动：web_search/)).toBeInTheDocument();
  expect(screen.getByText(/状态更新：task/)).toBeInTheDocument();
  expect(screen.getByText("search_attempts: 0 → 1")).toBeInTheDocument();
});

it("shows an empty state when there are no trajectory events", () => {
  render(<DecisionTrace events={[{ id: 1, type: "run.started", timestamp: "2026-08-11T09:00:00Z", data: {} }]} />);

  expect(screen.getByText("暂无决策轨迹。")).toBeInTheDocument();
});
