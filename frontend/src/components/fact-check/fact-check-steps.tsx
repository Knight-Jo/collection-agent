import { CheckCircle2, CircleDashed } from "lucide-react";
import type { FactCheckStep } from "@/api/types";

const PHASE_LABELS: Record<string, string> = {
  queued: "已提交",
  understanding: "理解断言",
  researching: "检索取证",
  adjudicating: "形成裁决",
  done: "完成",
};

const STATE_LABELS: Record<string, string> = {
  submitted: "排队中",
  started: "进行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
};

export function FactCheckSteps({ steps }: { steps: FactCheckStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground">
        <CircleDashed className="size-4" />
        暂无核验轨迹
      </div>
    );
  }

  return (
    <ol className="space-y-2">
      {steps.map((step) => (
        <li
          key={step.id}
          className="flex items-start gap-3 rounded-lg border bg-card p-3"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {PHASE_LABELS[step.phase] ?? step.phase}
              </span>
              {step.state && (
                <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground">
                  {STATE_LABELS[step.state] ?? step.state}
                </span>
              )}
            </div>
            {step.summary && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {step.summary}
              </p>
            )}
            {step.at && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {new Date(step.at).toLocaleString("zh-CN")}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
