import { AlertTriangle, CheckCircle2, CircleDashed, LoaderCircle } from "lucide-react";
import type { ResearchGap, ResearchQuestion } from "@/api/types";
import { Badge } from "@/components/ui/badge";

const STATUS_META: Record<
  ResearchQuestion["status"],
  { label: string; icon: typeof CircleDashed }
> = {
  pending: { label: "待研究", icon: CircleDashed },
  researching: { label: "研究中", icon: LoaderCircle },
  answered: { label: "已回答", icon: CheckCircle2 },
  blocked: { label: "证据不足", icon: AlertTriangle },
};

export function ResearchStructure({
  questions,
  gaps,
}: {
  questions: ResearchQuestion[];
  gaps: ResearchGap[];
}) {
  const gapByQuestion = new Map(gaps.map((gap) => [gap.question_id, gap]));

  return (
    <div className="space-y-4 p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        研究结构
      </h2>
      {questions.map((question, index) => {
        const meta = STATUS_META[question.status];
        const Icon = meta.icon;
        const gap = gapByQuestion.get(question.id);
        return (
          <div key={question.id} className="rounded-lg border bg-card p-3">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 text-xs font-semibold text-primary">Q{index + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{question.text}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Badge
                    variant={question.status === "blocked" ? "secondary" : "outline"}
                    className={
                      question.status === "blocked"
                        ? "bg-destructive/10 text-destructive"
                        : undefined
                    }
                  >
                    <Icon className="size-3" />
                    {meta.label}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    证据 {question.evidence_count}
                  </span>
                </div>
                {question.coverage_note && (
                  <p className="mt-1.5 text-xs text-muted-foreground">{question.coverage_note}</p>
                )}
              </div>
            </div>
            {gap && (
              <div className="mt-2 rounded-md border border-dashed p-2 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">缺口</p>
                <p className="mt-0.5">{gap.reason}</p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
