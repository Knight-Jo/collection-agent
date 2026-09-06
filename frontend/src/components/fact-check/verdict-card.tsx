import {
  CircleCheck,
  CircleX,
  HelpCircle,
  MinusCircle,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { EvidenceSufficiency, FactCheck, Verdict } from "@/api/types";
import { cn } from "@/lib/utils";

const VERDICT_META: Record<Verdict, { label: string; icon: typeof ShieldCheck; tone: string }> = {
  supported: {
    label: "支持",
    icon: ShieldCheck,
    tone: "border-sky-200 bg-sky-50 text-sky-700",
  },
  mostly_supported: {
    label: "基本支持",
    icon: CircleCheck,
    tone: "border-sky-200 bg-sky-50 text-sky-700",
  },
  insufficient: {
    label: "证据不足",
    icon: MinusCircle,
    tone: "border-amber-200 bg-amber-50 text-amber-700",
  },
  disputed: {
    label: "存在争议",
    icon: ShieldAlert,
    tone: "border-amber-200 bg-amber-50 text-amber-700",
  },
  mostly_refuted: {
    label: "基本不支持",
    icon: CircleX,
    tone: "border-red-200 bg-red-50 text-red-700",
  },
  refuted: { label: "错误", icon: CircleX, tone: "border-red-200 bg-red-50 text-red-700" },
};

const SUFFICIENCY_LABELS: Record<EvidenceSufficiency, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

export function VerdictCard({ factCheck }: { factCheck: FactCheck }) {
  if (factCheck.status === "running") {
    return (
      <div className="rounded-lg border bg-card p-4">
        <p className="text-xs text-muted-foreground">核验结论</p>
        <p className="mt-1 flex items-center gap-2 text-sm">
          <HelpCircle className="size-4 text-muted-foreground" />
          核验进行中…
        </p>
      </div>
    );
  }

  const verdict = factCheck.verdict ?? "insufficient";
  const meta = VERDICT_META[verdict];
  const Icon = meta.icon;

  return (
    <div className={cn("rounded-lg border p-4", meta.tone)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className="size-5" />
          <span className="text-lg font-semibold">{meta.label}</span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span>
            证据充分度：
            <strong>
              {factCheck.evidence_sufficiency
                ? SUFFICIENCY_LABELS[factCheck.evidence_sufficiency]
                : "—"}
            </strong>
          </span>
          <span>独立来源 {factCheck.independent_sources}</span>
          <span>原始来源 {factCheck.primary_sources}</span>
          <span>反证 {factCheck.counter_evidence}</span>
        </div>
      </div>
      {factCheck.rationale && (
        <p className="mt-3 border-t pt-2 text-xs leading-relaxed opacity-80">
          {factCheck.rationale}
        </p>
      )}
    </div>
  );
}
