import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, LayoutGrid, LoaderCircle, Radar } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversations } from "@/hooks/use-conversations";
import { useFactChecks } from "@/hooks/use-fact-checks";
import { useMonitors } from "@/hooks/use-monitors";
import { useSystem } from "@/hooks/use-system";

const ACTIVE_RUN = ["queued", "running", "stopping"];

export const Route = createFileRoute("/")({
  component: Dashboard,
});

function Dashboard() {
  const { data: conversations, isLoading: loadingConversations } = useConversations(false);
  const { data: monitors } = useMonitors();
  const { data: factChecks } = useFactChecks();
  const { data: system } = useSystem();

  const running = (conversations ?? []).filter((item) =>
    ACTIVE_RUN.includes(item.run_status ?? ""),
  );
  const intake = (conversations ?? []).filter((item) => item.status === "intake");
  const runningChecks = (factChecks ?? []).filter((item) => item.status === "running");
  const completed = [...(conversations ?? [])]
    .filter((item) => item.run_status === "succeeded")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 4);
  const recentMonitors = (monitors ?? [])
    .filter((item) => item.last_run_at !== null)
    .sort((a, b) => (b.last_run_at ?? "").localeCompare(a.last_run_at ?? ""))
    .slice(0, 4);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-center gap-2">
          <LayoutGrid className="size-6 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">情报态势</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          正在发生什么、什么需要你处理、什么刚发生变化。
        </p>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Section
            title="正在运行"
            icon={<LoaderCircle className="size-4 animate-spin text-primary" />}
          >
            {running.map((item) => (
              <Link
                key={item.id}
                to="/research/$conversationId"
                params={{ conversationId: item.id }}
                className="block rounded-lg border bg-card p-3 transition-shadow hover:shadow-sm"
              >
                <p className="truncate text-sm font-medium">{item.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  研究进行中 · {item.run_phase === "collecting" ? "收集材料" : "制定计划"}
                </p>
              </Link>
            ))}
            {(monitors ?? [])
              .filter((item) => item.status === "active")
              .map((item) => (
                <Link
                  key={item.id}
                  to="/monitor/$monitorId"
                  params={{ monitorId: item.id }}
                  className="flex items-center gap-2 rounded-lg border bg-card p-3 text-sm transition-shadow hover:shadow-sm"
                >
                  <Radar className="size-4 text-primary" />
                  <span className="truncate font-medium">{item.name}</span>
                  <Badge variant="secondary" className="ml-auto">
                    监测中
                  </Badge>
                </Link>
              ))}
            {running.length === 0 && !monitors?.some((m) => m.status === "active") && (
              <Empty text="暂无正在运行的任务" />
            )}
          </Section>

          <Section title="需要关注" icon={<AlertTriangle className="size-4 text-destructive" />}>
            {intake.map((item) => (
              <Link
                key={item.id}
                to="/research/$conversationId"
                params={{ conversationId: item.id }}
                className="block rounded-lg border bg-card p-3 text-sm transition-shadow hover:shadow-sm"
              >
                <span className="truncate font-medium">{item.title}</span>
                <p className="mt-1 text-xs text-muted-foreground">待明确调研目标</p>
              </Link>
            ))}
            {runningChecks.map((item) => (
              <Link
                key={item.id}
                to="/fact-check/$checkId"
                params={{ checkId: item.id }}
                className="block rounded-lg border bg-card p-3 text-sm transition-shadow hover:shadow-sm"
              >
                <span className="line-clamp-1 font-medium">{item.claim}</span>
                <p className="mt-1 text-xs text-muted-foreground">核验进行中</p>
              </Link>
            ))}
            {intake.length === 0 && runningChecks.length === 0 && (
              <Empty text="暂无需要关注的事项" />
            )}
          </Section>

          <Section title="最近变化" icon={<Radar className="size-4 text-primary" />}>
            {recentMonitors.map((item) => (
              <Link
                key={item.id}
                to="/monitor/$monitorId"
                params={{ monitorId: item.id }}
                className="block rounded-lg border bg-card p-3 text-sm transition-shadow hover:shadow-sm"
              >
                <span className="truncate font-medium">{item.name}</span>
                <p className="mt-1 text-xs text-muted-foreground">
                  最近运行{" "}
                  {item.last_run_at ? new Date(item.last_run_at).toLocaleString("zh-CN") : "—"}
                </p>
              </Link>
            ))}
            {recentMonitors.length === 0 && <Empty text="暂无监测变化" />}
          </Section>

          <Section title="最近完成" icon={<CheckCircle2 className="size-4 text-primary" />}>
            {completed.map((item) => (
              <Link
                key={item.id}
                to="/research/$conversationId"
                params={{ conversationId: item.id }}
                className="block rounded-lg border bg-card p-3 text-sm transition-shadow hover:shadow-sm"
              >
                <span className="truncate font-medium">{item.title}</span>
                <p className="mt-1 text-xs text-muted-foreground">报告已完成</p>
              </Link>
            ))}
            {completed.length === 0 && <Empty text="暂无已完成的研究" />}
          </Section>
        </div>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">系统状态</h2>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatusCard
              label="模型"
              value={system?.model.name ?? "—"}
              ok={system?.model.configured}
            />
            <StatusCard
              label="搜索源"
              value={system?.search.name ?? "—"}
              ok={system?.search.configured}
            />
            <StatusCard
              label="解析器"
              value={
                system
                  ? ["OCR", "音视频", "文档"]
                      .filter(
                        (_, i) =>
                          [
                            system.processors.tesseract,
                            system.processors.ffmpeg,
                            system.processors.whisper,
                          ][i],
                      )
                      .join(" · ") || "未配置"
                  : "—"
              }
              ok
            />
          </div>
        </section>

        {loadingConversations && (
          <div className="absolute inset-0 grid place-items-center">
            <Skeleton className="h-10 w-40" />
          </div>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        {icon}
        {title}
      </h2>
      <div className="mt-2 space-y-2">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">{text}</p>
  );
}

function StatusCard({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 flex items-center gap-2 text-sm font-medium">
        <span className={`size-2 rounded-full ${ok ? "bg-sky-500" : "bg-amber-500"}`} />
        {value}
      </p>
    </div>
  );
}
