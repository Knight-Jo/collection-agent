import { createFileRoute } from "@tanstack/react-router";
import { Settings } from "lucide-react";
import type { ReactNode } from "react";
import { AiSearchTools } from "@/components/settings/ai-search-tools";
import { SearchSourceManager } from "@/components/settings/search-source-manager";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useSystem } from "@/hooks/use-system";

export const Route = createFileRoute("/settings/")({
  component: SettingsIndex,
});

function SettingsIndex() {
  const { data: system } = useSystem();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl px-6 py-8">
        <div className="flex items-center gap-2">
          <Settings className="size-6 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">系统设置</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          面向用户的偏好设置；后端服务状态归类在「服务与解析器」。
        </p>

        <section className="mt-6">
          <h2 className="text-sm font-semibold text-muted-foreground">用户偏好</h2>
          <div className="mt-3 space-y-3">
            <SettingRow title="默认模型" description="生成回答与报告使用的模型">
              <span className="text-sm">
                {system ? system.model.name : <Skeleton className="h-4 w-24" />}
              </span>
            </SettingRow>
            <SettingRow title="默认搜索源" description="检索公开信息使用的搜索源">
              <span className="text-sm">
                {system ? system.search.name : <Skeleton className="h-4 w-24" />}
              </span>
            </SettingRow>
            <SettingRow title="报告模板" description="报告生成采用的章节结构">
              <span className="text-sm text-muted-foreground">标准模板</span>
            </SettingRow>
            <SettingRow title="变化通知" description="监测发现重要变化时提醒">
              <Switch defaultChecked aria-label="变化通知" />
            </SettingRow>
          </div>
        </section>

        <Separator className="my-8" />

        <section>
          <h2 className="text-sm font-semibold text-muted-foreground">搜索来源</h2>
          <div className="mt-3">
            <SearchSourceManager />
          </div>
        </section>

        <Separator className="my-8" />

        <section>
          <h2 className="text-sm font-semibold text-muted-foreground">AI 搜索工具</h2>
          <div className="mt-3">
            <AiSearchTools />
          </div>
        </section>

        <Separator className="my-8" />

        <section>
          <h2 className="text-sm font-semibold text-muted-foreground">服务与解析器</h2>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <ServiceCard
              title="模型服务"
              value={system ? (system.model.configured ? "已配置" : "未配置") : undefined}
              ok={system?.model.configured}
            />
            <ServiceCard
              title="搜索源"
              value={system ? (system.search.configured ? "已配置" : "未配置") : undefined}
              ok={system?.search.configured}
            />
            <ServiceCard
              title="OCR / 音视频"
              value={
                system
                  ? [system.processors.tesseract, system.processors.ffmpeg].every(Boolean)
                    ? "可用"
                    : "部分可用"
                  : undefined
              }
              ok={system?.processors.tesseract}
            />
          </div>
        </section>
      </div>
    </div>
  );
}

function SettingRow({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border bg-card p-4">
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  );
}

function ServiceCard({ title, value, ok }: { title: string; value?: string; ok?: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {value === undefined ? (
          <Skeleton className="h-4 w-16" />
        ) : (
          <div className="flex items-center gap-2">
            <span className={`size-2 rounded-full ${ok ? "bg-sky-500" : "bg-amber-500"}`} />
            <CardDescription>{value}</CardDescription>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
