import { ExternalLink } from "lucide-react";
import type { LibraryResearchRecord } from "@/api/types";
import { AgentTimeline } from "@/components/research/agent-timeline";
import { MaterialsList } from "@/components/research/materials-list";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ReportView } from "./report-view";

export function TaskAssets({ task }: { task: LibraryResearchRecord }) {
  return (
    <Tabs defaultValue="process">
      <TabsList>
        <TabsTrigger value="process">过程</TabsTrigger>
        <TabsTrigger value="report">报告 ({task.report ? 1 : 0})</TabsTrigger>
        <TabsTrigger value="materials">材料 ({task.materials.length})</TabsTrigger>
        <TabsTrigger value="facts">事实 ({task.facts.length})</TabsTrigger>
        <TabsTrigger value="evidence">证据 ({task.evidence.length})</TabsTrigger>
        <TabsTrigger value="sources">来源 ({task.sources.length})</TabsTrigger>
      </TabsList>

      <TabsContent value="process" className="mt-4 space-y-4">
        {task.brief && (
          <div className="rounded-lg border bg-card p-3">
            <p className="text-xs font-semibold text-muted-foreground">调研简报</p>
            <p className="mt-1 text-sm font-medium">{task.brief.goal}</p>
            <p className="mt-1 text-xs text-muted-foreground">{task.brief.scope}</p>
          </div>
        )}
        {task.questions.length > 0 && (
          <div className="rounded-lg border bg-card p-3">
            <p className="text-xs font-semibold text-muted-foreground">关键问题</p>
            <ul className="mt-1 space-y-1">
              {task.questions.map((question) => (
                <li key={question.id} className="flex items-start gap-2 text-sm">
                  <Badge variant={question.status === "answered" ? "default" : "secondary"}>
                    {question.status === "answered" ? "已回答" : "待研究"}
                  </Badge>
                  {question.text}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">研究轨迹</p>
          <AgentTimeline entries={task.timeline} />
        </div>
      </TabsContent>

      <TabsContent value="report" className="mt-4">
        {task.report ? (
          <ReportView report={task.report} />
        ) : (
          <p className="px-1 py-6 text-sm text-muted-foreground">调研尚未生成报告</p>
        )}
      </TabsContent>

      <TabsContent value="materials" className="mt-4">
        <MaterialsList materials={task.materials} />
      </TabsContent>

      <TabsContent value="facts" className="mt-4">
        <ul className="space-y-3">
          {task.facts.map((fact) => (
            <li key={fact.id} className="rounded-lg border bg-card p-3">
              <p className="text-sm">{fact.statement}</p>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant={fact.status === "accepted" ? "default" : "secondary"}>
                  {fact.status === "accepted" ? "已采纳" : "存在争议"}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {new Date(fact.updated_at).toLocaleString("zh-CN")}
                </span>
              </div>
            </li>
          ))}
          {task.facts.length === 0 && (
            <p className="px-1 py-6 text-sm text-muted-foreground">暂无事实</p>
          )}
        </ul>
      </TabsContent>

      <TabsContent value="evidence" className="mt-4">
        <ul className="space-y-3">
          {task.evidence.map((item) => (
            <li key={item.id} className="rounded-lg border bg-card p-3">
              <div className="flex items-center gap-2">
                <Badge
                  variant={item.relation === "supports" ? "default" : "secondary"}
                  className={
                    item.relation === "contradicts"
                      ? "bg-destructive/10 text-destructive"
                      : undefined
                  }
                >
                  {item.relation === "supports" ? "支持" : "反驳"}
                </Badge>
                <span className="truncate text-sm font-medium">{item.source_title}</span>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">{item.quote}</p>
            </li>
          ))}
          {task.evidence.length === 0 && (
            <p className="px-1 py-6 text-sm text-muted-foreground">暂无证据</p>
          )}
        </ul>
      </TabsContent>

      <TabsContent value="sources" className="mt-4">
        <ul className="space-y-3">
          {task.sources.map((source) => (
            <li
              key={source.id}
              className="flex items-center justify-between gap-3 rounded-lg border bg-card p-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{source.name}</p>
                <p className="text-xs text-muted-foreground">{source.type}</p>
              </div>
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
              >
                打开
                <ExternalLink className="size-3" />
              </a>
            </li>
          ))}
          {task.sources.length === 0 && (
            <p className="px-1 py-6 text-sm text-muted-foreground">暂无来源</p>
          )}
        </ul>
      </TabsContent>
    </Tabs>
  );
}
