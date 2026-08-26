import { LoaderCircle, Search, Square } from "lucide-react";
import type { ResearchRun } from "../types";

const PHASE_LABELS = {
  planning: "正在制定检索计划",
  collecting: "正在收集材料",
  assessing: "正在评估证据",
  checkpointing: "正在提交研究结果",
};

export function RunStatusCard({
  run,
  committedStateVersion,
  busy,
  onStop,
  onCancel,
  onOpen,
}: {
  run: ResearchRun;
  committedStateVersion: number;
  busy: boolean;
  onStop: () => void;
  onCancel: () => void;
  onOpen: () => void;
}) {
  const running = run.status === "running" || run.status === "stopping";
  return (
    <article className="run-status-card">
      <header className="run-status-card__header">
        {running ? <LoaderCircle className="spin" size={18} /> : <Search size={18} />}
        <strong>{run.status === "stopping" ? "正在停止" : "调研进行中"}</strong>
      </header>
      <p>已提交：研究状态 v{committedStateVersion}</p>
      <p>当前运行：{PHASE_LABELS[run.phase ?? "planning"]}</p>
      <footer className="run-status-card__footer">
        <button type="button" className="text-button" onClick={onOpen}>
          查看运行详情
        </button>
        {run.status === "queued" ? (
          <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>
            取消排队
          </button>
        ) : (
          <button
            type="button"
            className="secondary-button"
            disabled={busy || run.status === "stopping"}
            onClick={onStop}
          >
            <Square size={13} />
            停止当前调研
          </button>
        )}
      </footer>
    </article>
  );
}
