import {
  CheckCircle2,
  CircleDashed,
  FileSearch,
  Lightbulb,
  ListTree,
  PackageSearch,
  Scale,
  Sparkles,
} from "lucide-react";
import type { TimelineEntry, TimelineKind } from "@/api/types";

const ICONS: Record<TimelineKind, typeof Lightbulb> = {
  intent: Lightbulb,
  search_plan: ListTree,
  search: FileSearch,
  material: PackageSearch,
  evidence: Scale,
  coverage: Sparkles,
  decision: CheckCircle2,
};

export function AgentTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground">
        <CircleDashed className="size-4" />
        暂无运行轨迹
      </div>
    );
  }

  return (
    <ol className="relative space-y-1">
      {entries.map((entry, index) => {
        const Icon = ICONS[entry.kind];
        return (
          <li key={entry.id} className="relative flex gap-3 pb-4 pl-1">
            {index < entries.length - 1 && (
              <span className="absolute left-[15px] top-7 h-[calc(100%-16px)] w-px bg-border" />
            )}
            <span className="grid size-8 shrink-0 place-items-center rounded-full border bg-card">
              <Icon className="size-4 text-primary" />
            </span>
            <div className="min-w-0 pt-1">
              <p className="text-sm font-medium">{entry.label}</p>
              {entry.detail && <p className="text-xs text-muted-foreground">{entry.detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
