import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { Aperture, Compass, History, LoaderCircle, Sparkles } from "lucide-react";
import { useState } from "react";
import type { ResearchBrief } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useGenerateBrief, useStartResearch } from "@/hooks/use-conversations";
import { useLibrary } from "@/hooks/use-system";

export const Route = createFileRoute("/research/")({
  component: ResearchIndex,
});

function ResearchIndex() {
  const navigate = useNavigate();
  const generateBrief = useGenerateBrief();
  const startResearch = useStartResearch();
  const { data: library, isLoading: loadingHistory } = useLibrary();
  const [prompt, setPrompt] = useState("");
  const [brief, setBrief] = useState<ResearchBrief | null>(null);
  const [error, setError] = useState<string | null>(null);

  function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  async function onGenerate() {
    const value = prompt.trim();
    if (!value) return;
    setError(null);
    try {
      setBrief(await generateBrief.mutateAsync(value));
    } catch (error) {
      setError(`生成调研简报失败：${errorMessage(error)}`);
    }
  }

  async function onStart() {
    if (!brief) return;
    setError(null);
    try {
      const conversation = await startResearch.mutateAsync({ topic: prompt.trim(), brief });
      await navigate({
        to: "/research/$conversationId",
        params: { conversationId: conversation.id },
      });
    } catch (error) {
      setError(`创建调研失败：${errorMessage(error)}`);
    }
  }

  if (!brief) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-xl px-6 py-10">
          <Aperture className="size-10 text-primary" />
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">深度调研</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            一句话描述你想系统研究的问题，系统先生成调研简报，再逐步展开研究过程。
          </p>
          <div className="mt-6 space-y-3">
            <Textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="例如：调研先进封装产业链及主要厂商"
              rows={3}
            />
            <Button
              className="w-full"
              onClick={onGenerate}
              disabled={!prompt.trim() || generateBrief.isPending}
            >
              {generateBrief.isPending ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Sparkles />
              )}
              {generateBrief.isPending ? "生成中" : "生成调研简报"}
            </Button>
          </div>
          {error && (
            <p className="mt-3 text-sm text-destructive" role="alert">
              {error}
            </p>
          )}

          <section className="mt-10">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
              <History className="size-4" />
              历史调研
            </h2>
            <div className="mt-3 space-y-2">
              {loadingHistory && (
                <div className="space-y-2">
                  <Skeleton className="h-14 w-full" />
                  <Skeleton className="h-14 w-full" />
                </div>
              )}
              {library?.research.map((record) => (
                <Link
                  key={record.id}
                  to="/library"
                  search={{ dim: "research", id: record.id }}
                  className="block rounded-lg border bg-card p-3 transition-shadow hover:shadow-sm"
                >
                  <p className="truncate text-sm font-medium">{record.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {record.report ? "报告已完成" : "调研进行中"} · 材料 {record.materials.length} ·
                    事实 {record.facts.length}
                  </p>
                </Link>
              ))}
              {!loadingHistory && library?.research.length === 0 && (
                <p className="text-sm text-muted-foreground">暂无历史调研记录</p>
              )}
            </div>
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Compass className="size-4 text-primary" />
          调研简报
        </div>
        <h1 className="mt-2 text-xl font-semibold tracking-tight">{brief.goal}</h1>

        <div className="mt-6 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">研究范围</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">{brief.scope}</CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">关键问题</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1">
                {brief.questions.map((question, index) => (
                  <li key={question} className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 text-primary">Q{index + 1}</span>
                    {question}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">建议来源类型</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {brief.suggested_sources.map((source) => (
                <span
                  key={source}
                  className="rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground"
                >
                  {source}
                </span>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="mt-6 flex gap-3">
          <Button variant="outline" onClick={() => setBrief(null)}>
            返回修改
          </Button>
          <Button onClick={onStart} disabled={startResearch.isPending} className="flex-1">
            {startResearch.isPending ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <Sparkles />
            )}
            {startResearch.isPending ? "创建中" : "开始调研"}
          </Button>
        </div>
        {error && (
          <p className="mt-3 text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
