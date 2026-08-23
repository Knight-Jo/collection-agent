import { CheckCircle2, CircleEllipsis, XCircle } from "lucide-react";
import type { RunEvent } from "../types";

function crawlResourceStatus(event: RunEvent) {
  return event.type === "crawl.resource"
    ? String((event.data.resource as { status?: unknown } | undefined)?.status ?? "")
    : "";
}

function eventLabel(event: RunEvent) {
  if (event.type === "crawl.progress") {
    const counts = event.data.counts as Record<string, number> | undefined;
    const completed = (counts?.complete ?? 0) + (counts?.reused ?? 0);
    return `深度抓取进度：已完成 ${completed}，待处理 ${counts?.queued ?? 0}`;
  }
  if (event.type === "crawl.resource") {
    const status = crawlResourceStatus(event);
    if (status === "failed") return "抓取资源失败";
    if (status.startsWith("skipped_")) return "已跳过抓取资源";
  }
  return (
    {
      "run.started": "研究任务已启动",
      "task.updated": "任务状态已更新",
      "run.completed": "研究任务已完成",
      "run.cancelled": "研究任务已停止",
      "run.failed": "研究任务执行失败",
      "crawl.started": "正在开始深度抓取",
      "crawl.resource": "已发现抓取资源",
      "crawl.completed": "深度抓取已完成",
    }[event.type] ?? "研究进度已更新"
  );
}

export function RunTimeline({ events }: { events: RunEvent[] }) {
  const timeline = events.filter((event) => !event.type.startsWith("trajectory."));
  if (!timeline.length) return <p className="muted">等待任务启动…</p>;
  return (
    <ol className="timeline" aria-label="实时进度">
      {timeline.map((event) => {
        const resourceStatus = crawlResourceStatus(event);
        const skipped = resourceStatus.startsWith("skipped_");
        const failed =
          event.type === "run.failed" ||
          event.type === "run.cancelled" ||
          resourceStatus === "failed";
        const running = ["run.started", "crawl.started", "crawl.progress"].includes(event.type);
        const Icon = failed ? XCircle : running || skipped ? CircleEllipsis : CheckCircle2;
        return (
          <li
            key={event.id}
            data-state={failed ? "failed" : skipped ? "skipped" : running ? "running" : "completed"}
          >
            <Icon size={18} />
            <div>
              <strong>{eventLabel(event)}</strong>
              <time>{new Date(event.timestamp).toLocaleTimeString("zh-CN")}</time>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
