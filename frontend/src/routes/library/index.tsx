import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { BookOpen } from "lucide-react";
import type { FactCheck, LibraryResearchRecord, MonitorDetail } from "@/api/types";
import { FactCheckRecord } from "@/components/library/fact-check-record";
import { MonitorRecord } from "@/components/library/monitor-record";
import { TaskAssets } from "@/components/library/task-assets";
import { TaskList } from "@/components/library/task-list";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLibrary } from "@/hooks/use-system";
import { cn } from "@/lib/utils";

type Dim = "research" | "monitor" | "fact-check";

const DIMS: Dim[] = ["research", "monitor", "fact-check"];

const VERDICT_LABELS: Record<string, string> = {
  supported: "支持",
  mostly_supported: "基本支持",
  insufficient: "证据不足",
  disputed: "存在争议",
  mostly_refuted: "基本不支持",
  refuted: "错误",
};

export const Route = createFileRoute("/library/")({
  validateSearch: (search: Record<string, unknown>): { dim?: Dim; id?: string } => {
    const dimValue = search.dim as Dim | undefined;
    const idValue = search.id as string | undefined;
    const result: { dim?: Dim; id?: string } = {};
    if (dimValue && DIMS.includes(dimValue)) result.dim = dimValue;
    if (idValue && idValue.length > 0) result.id = idValue;
    return result;
  },
  component: LibraryIndex,
});

function LibraryIndex() {
  const navigate = useNavigate();
  const search = Route.useSearch();
  const { data, isLoading } = useLibrary();
  const dim: Dim = search.dim ?? "research";

  if (isLoading || !data) {
    return (
      <div className="mx-auto max-w-4xl space-y-3 px-6 py-8">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  function switchDim(next: Dim) {
    void navigate({ to: "/library", search: { dim: next } });
  }

  function select(nextId: string) {
    void navigate({ to: "/library", search: { dim, id: nextId } });
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <BookOpen className="size-5 text-primary" />
          <h1 className="text-base font-semibold tracking-tight">情报资料库</h1>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          三个维度的历史记录与历史过程，统一在此沉淀
        </p>
        <Tabs value={dim} onValueChange={(value) => switchDim(value as Dim)} className="mt-3">
          <TabsList>
            <TabsTrigger value="research">深度调研 ({data.research.length})</TabsTrigger>
            <TabsTrigger value="monitor">持续监测 ({data.monitors.length})</TabsTrigger>
            <TabsTrigger value="fact-check">事实核验 ({data.factChecks.length})</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-72 shrink-0 flex-col border-r">
          <ScrollArea className="flex-1">
            <div className="px-2 py-3">
              {dim === "research" && (
                <TaskList tasks={data.research} selectedId={search.id ?? null} onSelect={select} />
              )}
              {dim === "monitor" && (
                <ul className="space-y-1">
                  {data.monitors.map(({ monitor }) => (
                    <li key={monitor.id}>
                      <button
                        type="button"
                        onClick={() => select(monitor.id)}
                        className={cn(
                          "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
                          monitor.id === (search.id ?? data.monitors[0]?.monitor.id) &&
                            "bg-sidebar-accent text-sidebar-accent-foreground",
                        )}
                      >
                        <p className="truncate text-sm font-medium">{monitor.name}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">{monitor.subject}</p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {dim === "fact-check" && (
                <ul className="space-y-1">
                  {data.factChecks.map((check) => (
                    <li key={check.id}>
                      <button
                        type="button"
                        onClick={() => select(check.id)}
                        className={cn(
                          "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
                          check.id === (search.id ?? data.factChecks[0]?.id) &&
                            "bg-sidebar-accent text-sidebar-accent-foreground",
                        )}
                      >
                        <p className="line-clamp-2 text-sm font-medium">{check.claim}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {check.verdict ? VERDICT_LABELS[check.verdict] : "核验中"}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </ScrollArea>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {dim === "research" && <ResearchDetail data={data.research} id={search.id} />}
            {dim === "monitor" && <MonitorPane data={data.monitors} id={search.id} />}
            {dim === "fact-check" && <FactCheckDetail data={data.factChecks} id={search.id} />}
          </div>
        </main>
      </div>
    </div>
  );
}

function ResearchDetail({ data, id }: { data: LibraryResearchRecord[]; id?: string }) {
  const record = data.find((item) => item.id === id) ?? data[0];
  if (!record) {
    return <p className="py-16 text-center text-sm text-muted-foreground">暂无深度调研记录</p>;
  }
  return (
    <>
      <h2 className="text-xl font-semibold tracking-tight">{record.title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        更新于 {new Date(record.updated_at).toLocaleString("zh-CN")}
      </p>
      <div className="mt-6">
        <TaskAssets task={record} />
      </div>
    </>
  );
}

function MonitorPane({ data, id }: { data: MonitorDetail[]; id?: string }) {
  const record = data.find((item) => item.monitor.id === id) ?? data[0];
  if (!record) {
    return <p className="py-16 text-center text-sm text-muted-foreground">暂无持续监测记录</p>;
  }
  return (
    <>
      <h2 className="text-xl font-semibold tracking-tight">{record.monitor.name}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{record.monitor.subject}</p>
      <div className="mt-6">
        <MonitorRecord detail={record} />
      </div>
    </>
  );
}

function FactCheckDetail({ data, id }: { data: FactCheck[]; id?: string }) {
  const record = data.find((item) => item.id === id) ?? data[0];
  if (!record) {
    return <p className="py-16 text-center text-sm text-muted-foreground">暂无事实核验记录</p>;
  }
  return (
    <>
      <h2 className="text-xl font-semibold tracking-tight">{record.claim}</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        核验于 {new Date(record.created_at).toLocaleString("zh-CN")}
      </p>
      <div className="mt-6">
        <FactCheckRecord check={record} />
      </div>
    </>
  );
}
