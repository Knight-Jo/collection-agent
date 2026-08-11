import { CheckCircle2, CircleEllipsis, XCircle } from "lucide-react";
import type { RunEvent } from "../types";

const toolLabels: Record<string, [string, string]> = {
  intel_plan: ["正在制定研究计划", "研究计划已建立"],
  web_search: ["正在检索公开来源", "公开来源检索已完成"],
  web_fetch: ["正在抓取并归档文档", "文档归档已完成"],
  fact_save: ["正在整理关键事实", "关键事实已保存"],
  evidence_save: ["正在绑定原文证据", "原文证据已保存"],
  evidence_audit: ["正在进行语义审核", "语义审核已完成"],
  coverage_eval: ["正在评估证据覆盖度", "覆盖度评估已完成"],
  intel_assess: ["正在形成综合研判", "综合研判已完成"],
  intel_challenge_start: ["正在发起红队复审", "红队复审已启动"],
  intel_challenge_confirm: ["正在确认复审结论", "复审结论已确认"],
  generate_package: ["正在生成证据包", "证据包已生成"],
};

function crawlResourceStatus(event: RunEvent) {
  return event.type === "crawl.resource"
    ? String((event.data.resource as { status?: unknown } | undefined)?.status ?? "")
    : "";
}

function eventLabel(event: RunEvent) {
  if (event.type.startsWith("tool.")) {
    const labels = toolLabels[String(event.data.tool_name)] ?? ["正在执行研究步骤", "研究步骤已完成"];
    return event.type === "tool.started" ? labels[0] : labels[1];
  }
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
  return {
    "run.started": "研究任务已启动",
    "task.updated": "任务状态已更新",
    "run.completed": "研究任务已完成",
    "run.cancelled": "研究任务已停止",
    "run.failed": "研究任务执行失败",
    "crawl.started": "正在开始深度抓取",
    "crawl.resource": "已发现抓取资源",
    "crawl.completed": "深度抓取已完成",
  }[event.type] ?? "研究进度已更新";
}

export function RunTimeline({ events }: { events: RunEvent[] }) {
  if (!events.length) return <p className="muted">等待任务启动…</p>;
  return (
    <ol className="timeline" aria-label="实时进度">
      {events.map((event) => {
        const resourceStatus = crawlResourceStatus(event);
        const skipped = resourceStatus.startsWith("skipped_");
        const failed = event.type === "run.failed" || event.type === "run.cancelled" || resourceStatus === "failed";
        const running = ["tool.started", "run.started", "crawl.started", "crawl.progress"].includes(event.type);
        const Icon = failed ? XCircle : running || skipped ? CircleEllipsis : CheckCircle2;
        return (
          <li key={event.id} data-state={failed ? "failed" : skipped ? "skipped" : running ? "running" : "completed"}>
            <Icon size={18} />
            <div><strong>{eventLabel(event)}</strong><time>{new Date(event.timestamp).toLocaleTimeString("zh-CN")}</time></div>
          </li>
        );
      })}
    </ol>
  );
}
