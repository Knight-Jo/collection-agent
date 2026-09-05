import { createFileRoute, Link } from "@tanstack/react-router";
import { ChevronRight, Plus, Radar } from "lucide-react";
import { useState } from "react";
import { MonitorForm } from "@/components/monitor/monitor-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMonitors } from "@/hooks/use-monitors";

export const Route = createFileRoute("/monitor/")({
  component: MonitorIndex,
});

function MonitorIndex() {
  const { data: monitors, isLoading } = useMonitors();
  const [open, setOpen] = useState(false);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Radar className="size-6 text-primary" />
              <h1 className="text-2xl font-semibold tracking-tight">持续监测</h1>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              长期盯住关键对象，持续发现并沉淀变化。
            </p>
          </div>
          <Button onClick={() => setOpen(true)}>
            <Plus />
            新建监测
          </Button>
        </div>

        <div className="mt-6 space-y-3">
          {isLoading && (
            <div className="space-y-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}
          {monitors?.map((monitor) => (
            <Card key={monitor.id} className="transition-shadow hover:shadow-sm">
              <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
                <Link
                  to="/monitor/$monitorId"
                  params={{ monitorId: monitor.id }}
                  className="min-w-0 flex-1"
                >
                  <CardTitle className="flex items-center gap-2">
                    <Radar className="size-4 text-primary" />
                    {monitor.name}
                    <Badge variant={monitor.status === "active" ? "default" : "secondary"}>
                      {monitor.status === "active" ? "监测中" : "已暂停"}
                    </Badge>
                  </CardTitle>
                  <CardDescription className="mt-1 truncate">
                    {monitor.subject} · {monitor.websites.length} 个网站
                  </CardDescription>
                </Link>
                <Link
                  to="/library"
                  search={{ dim: "monitor", id: monitor.id }}
                  className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
                >
                  查看记录
                  <ChevronRight className="size-3.5" />
                </Link>
              </CardHeader>
            </Card>
          ))}
        </div>
      </div>

      <MonitorForm open={open} onOpenChange={setOpen} />
    </div>
  );
}
