import { LoaderCircle, Search } from "lucide-react";
import type { Run, RunPhase } from "@/api/types";

const RUN_PHASE_LABELS: Record<RunPhase, string> = {
  planning: "正在制定检索计划",
  collecting: "正在收集材料",
  assessing: "正在评估证据",
  checkpointing: "正在提交研究结果",
};

export function RunStatus({ run }: { run: Run | null }) {
  if (!run) return null;
  const active = run.status === "queued" || run.status === "running";
  const failed = run.status === "failed";
  if (!active && !failed) return null;

  return (
    <div className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm">
      {failed ? (
        <Search className="size-4 text-destructive" />
      ) : (
        <LoaderCircle className="size-4 animate-spin text-primary" />
      )}
      <span className="font-medium">
        {failed ? "调研未完成" : run.status === "queued" ? "已排队" : "调研进行中"}
      </span>
      {run.phase && !failed && (
        <span className="text-muted-foreground">· {RUN_PHASE_LABELS[run.phase]}</span>
      )}
    </div>
  );
}
