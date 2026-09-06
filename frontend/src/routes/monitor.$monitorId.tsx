import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, Play } from "lucide-react";
import { ChangeHistory } from "@/components/monitor/change-history";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMonitor, useRunMonitorNow, useToggleMonitor } from "@/hooks/use-monitors";

export const Route = createFileRoute("/monitor/$monitorId")({
  component: MonitorDetail,
});

function MonitorDetail() {
  const { monitorId } = Route.useParams();
  const { data, isLoading } = useMonitor(monitorId);
  const toggleMonitor = useToggleMonitor();
  const runNow = useRunMonitorNow();

  if (isLoading || !data) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  const { monitor, runs } = data;
  const allChanges = runs.flatMap((run) => run.changes);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Link
          to="/monitor"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          返回持续监测
        </Link>

        <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              {monitor.name}
              <Badge variant={monitor.status === "active" ? "default" : "secondary"}>
                {monitor.status === "active" ? "监测中" : "已暂停"}
              </Badge>
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">{monitor.subject}</p>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              disabled={runNow.isPending}
              onClick={() => runNow.mutate(monitorId)}
            >
              <Play />
              立即运行
            </Button>
            <div className="flex items-center gap-2 text-sm">
              <Switch
                checked={monitor.status === "active"}
                onCheckedChange={() => toggleMonitor.mutate(monitorId)}
                aria-label={monitor.status === "active" ? "暂停监测" : "启用监测"}
              />
              暂停
            </div>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg border bg-card p-3">
            <dt className="text-xs text-muted-foreground">监测策略</dt>
            <dd className="mt-1 text-sm font-medium">{monitor.strategy || "—"}</dd>
          </div>
          <div className="rounded-lg border bg-card p-3">
            <dt className="text-xs text-muted-foreground">执行频率</dt>
            <dd className="mt-1 text-sm font-medium">{monitor.frequency}</dd>
          </div>
          <div className="rounded-lg border bg-card p-3">
            <dt className="text-xs text-muted-foreground">最近运行</dt>
            <dd className="mt-1 text-sm font-medium">
              {monitor.last_run_at
                ? new Date(monitor.last_run_at).toLocaleDateString("zh-CN")
                : "—"}
            </dd>
          </div>
        </div>

        {monitor.websites.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-semibold text-muted-foreground">监测网站</h3>
            <ul className="mt-2 space-y-1">
              {monitor.websites.map((website) => (
                <li key={website}>
                  <a
                    href={website}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                  >
                    {website}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}

        {monitor.questions.length > 0 && (
          <div className="mt-4">
            <ul className="flex flex-wrap gap-2">
              {monitor.questions.map((question) => (
                <li
                  key={question}
                  className="rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground"
                >
                  {question}
                </li>
              ))}
            </ul>
          </div>
        )}

        <section className="mt-8">
          <h2 className="text-lg font-semibold">最近发现</h2>
          <div className="mt-3">
            <Tabs defaultValue="changes">
              <TabsList>
                <TabsTrigger value="changes">变化时间轴</TabsTrigger>
                <TabsTrigger value="runs">运行历史</TabsTrigger>
              </TabsList>
              <TabsContent value="changes" className="mt-4">
                <ChangeHistory changes={allChanges} />
              </TabsContent>
              <TabsContent value="runs" className="mt-4">
                <ul className="space-y-3">
                  {runs.map((run) => (
                    <li key={run.id} className="rounded-lg border bg-card p-3">
                      <div className="flex items-center justify-between">
                        <Badge
                          variant={run.status === "succeeded" ? "default" : "secondary"}
                          className={
                            run.status === "failed"
                              ? "bg-destructive/10 text-destructive"
                              : undefined
                          }
                        >
                          {run.status === "succeeded" ? "成功" : "失败"}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {run.started_at ? new Date(run.started_at).toLocaleString("zh-CN") : "—"}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">{run.summary}</p>
                    </li>
                  ))}
                </ul>
              </TabsContent>
            </Tabs>
          </div>
        </section>
      </div>
    </div>
  );
}
