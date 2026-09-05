import type { LibraryTask } from "@/api/types";
import { cn } from "@/lib/utils";

export function TaskList({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: LibraryTask[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (tasks.length === 0) {
    return <p className="px-3 py-6 text-sm text-muted-foreground">暂无调研任务</p>;
  }

  return (
    <ul className="space-y-1">
      {tasks.map((task) => {
        const active = task.id === selectedId;
        return (
          <li key={task.id}>
            <button
              type="button"
              onClick={() => onSelect(task.id)}
              className={cn(
                "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
                active && "bg-sidebar-accent text-sidebar-accent-foreground",
              )}
            >
              <p className="truncate text-sm font-medium">{task.title}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {new Date(task.updated_at).toLocaleDateString("zh-CN")}
                <span className="mx-1.5">·</span>
                材料 {task.materials.length} · 事实 {task.facts.length} · 证据{" "}
                {task.evidence.length}
              </p>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
