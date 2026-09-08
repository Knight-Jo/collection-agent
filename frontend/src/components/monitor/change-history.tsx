import { AlertTriangle, FileMinus, FileText, RefreshCw } from "lucide-react";
import type { MonitorChange, MonitorChangeKind } from "@/api/types";
import { Badge } from "@/components/ui/badge";

const KIND_META: Record<MonitorChangeKind, { label: string; icon: typeof FileText }> = {
  new_fact: { label: "新增事实", icon: FileText },
  changed_fact: { label: "事实更新", icon: RefreshCw },
  removed_fact: { label: "事实撤销", icon: FileMinus },
  new_source: { label: "新增材料", icon: FileText },
};

export function ChangeHistory({ changes }: { changes: MonitorChange[] }) {
  if (changes.length === 0) {
    return <p className="px-1 py-6 text-sm text-muted-foreground">暂无变化记录</p>;
  }

  const sorted = [...changes].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <ol className="relative space-y-1">
      {sorted.map((change, index) => {
        const meta = KIND_META[change.kind];
        const Icon = meta.icon;
        return (
          <li key={change.id} className="relative flex gap-3 pb-4 pl-1">
            {index < sorted.length - 1 && (
              <span className="absolute left-[15px] top-7 h-[calc(100%-16px)] w-px bg-border" />
            )}
            <span className="grid size-8 shrink-0 place-items-center rounded-full border bg-card">
              <Icon className="size-4 text-primary" />
            </span>
            <div className="min-w-0 pt-1">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{meta.label}</Badge>
                {change.importance === "high" && (
                  <span className="inline-flex items-center gap-1 text-xs text-destructive">
                    <AlertTriangle className="size-3" />
                    重要变化
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm">{change.summary}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {new Date(change.at).toLocaleString("zh-CN")}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
