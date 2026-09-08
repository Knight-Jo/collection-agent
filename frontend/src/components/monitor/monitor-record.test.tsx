import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { MonitorChange, MonitorDetail, MonitorRun } from "@/api/types";
import { MonitorRecord } from "@/components/library/monitor-record";

function change(id: string, kind: MonitorChange["kind"]): MonitorChange {
  return {
    id,
    kind,
    importance: "normal",
    summary: `${kind} 事件`,
    at: "2026-01-01T00:00:00Z",
  };
}

function run(over: Partial<MonitorRun> = {}): MonitorRun {
  return {
    id: "r1",
    monitor_id: "m1",
    status: "succeeded",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:01:00Z",
    changes: [],
    summary: "闸门未检出变化，跳过研究循环",
    gate_outcome: "",
    ...over,
  };
}

function detail(over: Partial<MonitorDetail["monitor"]> = {}): MonitorDetail {
  return {
    monitor: {
      id: "m1",
      name: "Acme 舆情",
      subject: "Acme 公司动态",
      strategy: "track",
      frequency: "每天 09:00",
      status: "active",
      consecutive_failures: 0,
      next_run_at: null,
      last_run_at: null,
      created_at: "2026-01-01T00:00:00Z",
      questions: [],
      websites: ["https://example.com"],
      ...over,
    },
    runs: [run()],
  };
}

it("renders all four change kinds in the timeline", () => {
  const changes = [
    change("c1", "new_fact"),
    change("c2", "changed_fact"),
    change("c3", "removed_fact"),
    change("c4", "new_source"),
  ];
  render(<MonitorRecord detail={{ ...detail(), runs: [run({ changes })] }} />);
  expect(screen.getByText("新增事实")).toBeInTheDocument();
  expect(screen.getByText("事实更新")).toBeInTheDocument();
  expect(screen.getByText("事实撤销")).toBeInTheDocument();
  expect(screen.getByText("新增材料")).toBeInTheDocument();
});

it("shows the degraded badge with the consecutive failure count", () => {
  render(<MonitorRecord detail={detail({ status: "degraded", consecutive_failures: 3 })} />);
  expect(screen.getByText(/降级重试/)).toBeInTheDocument();
  expect(screen.getByText(/连续失败 3 次/)).toBeInTheDocument();
  expect(screen.queryByText("已暂停")).not.toBeInTheDocument();
});

it("shows the success badge and gate outcome in the run history", async () => {
  render(
    <MonitorRecord
      detail={{
        ...detail(),
        runs: [run({ gate_outcome: "skipped:unchanged=2" })],
      }}
    />,
  );
  await userEvent.click(screen.getByRole("tab", { name: /运行历史/ }));
  expect(screen.getByText("成功")).toBeInTheDocument();
  expect(screen.getByText("闸门：skipped:unchanged=2")).toBeInTheDocument();
  expect(screen.getByText(/跳过研究循环/)).toBeInTheDocument();
});

it("marks failed runs with the failure badge", async () => {
  render(<MonitorRecord detail={{ ...detail(), runs: [run({ status: "failed" })] }} />);
  await userEvent.click(screen.getByRole("tab", { name: /运行历史/ }));
  expect(screen.getByText("失败")).toBeInTheDocument();
});
