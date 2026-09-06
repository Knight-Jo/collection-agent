import type { MonitorDetail } from "@/api/types";
import { ChangeHistory } from "@/components/monitor/change-history";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function MonitorRecord({ detail }: { detail: MonitorDetail }) {
  const { monitor, runs } = detail;
  const allChanges = runs.flatMap((run) => run.changes);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card p-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{monitor.name}</span>
          <Badge variant={monitor.status === "active" ? "default" : "secondary"}>
            {monitor.status === "active" ? "监测中" : "已暂停"}
          </Badge>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{monitor.subject}</p>
        {monitor.strategy && (
          <p className="mt-1 text-xs text-muted-foreground">策略：{monitor.strategy}</p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">频率：{monitor.frequency}</p>
      </div>

      {monitor.websites.length > 0 && (
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">监测网站</p>
          <ul className="mt-1 space-y-1">
            {monitor.websites.map((website) => (
              <li key={website}>
                <a
                  href={website}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-sm text-primary hover:underline"
                >
                  {website}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Tabs defaultValue="changes">
        <TabsList>
          <TabsTrigger value="changes">变化时间轴 ({allChanges.length})</TabsTrigger>
          <TabsTrigger value="runs">运行历史 ({runs.length})</TabsTrigger>
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
                      run.status === "failed" ? "bg-destructive/10 text-destructive" : undefined
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
  );
}
