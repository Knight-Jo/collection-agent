import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { EvidenceTable } from "@/components/fact-check/evidence-table";
import { VerdictCard } from "@/components/fact-check/verdict-card";
import { AgentTimeline } from "@/components/research/agent-timeline";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useFactCheckStream } from "@/hooks/use-fact-check-stream";
import { useFactCheck } from "@/hooks/use-fact-checks";

export const Route = createFileRoute("/fact-check/$checkId")({
  component: FactCheckDetail,
});

function FactCheckDetail() {
  const { checkId } = Route.useParams();
  const { data, isLoading } = useFactCheck(checkId);
  useFactCheckStream(checkId);

  if (isLoading || !data) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Link
          to="/fact-check"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          返回事实核验
        </Link>

        <h1 className="mt-4 text-2xl font-semibold tracking-tight">{data.claim}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          核验于 {new Date(data.created_at).toLocaleString("zh-CN")}
        </p>

        {data.understanding && (
          <section className="mt-6">
            <h2 className="text-sm font-semibold text-muted-foreground">系统理解</h2>
            <p className="mt-1 text-sm">{data.understanding}</p>
          </section>
        )}

        {data.questions.length > 0 && (
          <section className="mt-4">
            <h2 className="text-sm font-semibold text-muted-foreground">核验问题</h2>
            <ul className="mt-1 space-y-1">
              {data.questions.map((question) => (
                <li key={question} className="flex items-start gap-2 text-sm">
                  <span className="mt-0.5 text-primary">›</span>
                  {question}
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="mt-6">
          <VerdictCard factCheck={data} />
        </div>

        {data.status === "running" && (
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            正在检索来源并核验证据…
          </div>
        )}

        <div className="mt-6">
          <Tabs defaultValue="evidence">
            <TabsList>
              <TabsTrigger value="evidence">正反证据</TabsTrigger>
              <TabsTrigger value="trajectory">核验轨迹</TabsTrigger>
            </TabsList>
            <TabsContent value="evidence" className="mt-4">
              <EvidenceTable evidence={data.evidence} />
            </TabsContent>
            <TabsContent value="trajectory" className="mt-4">
              <AgentTimeline entries={data.timeline} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
