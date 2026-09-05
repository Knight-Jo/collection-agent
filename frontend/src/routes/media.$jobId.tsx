import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { MediaFacts } from "@/components/media/media-facts";
import { TranscriptView } from "@/components/media/transcript-view";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaJob } from "@/hooks/use-media";
import { useMediaStream } from "@/hooks/use-media-stream";

const STATUS_LABELS: Record<string, string> = {
  transcribing: "转写中",
  analyzing: "分析中",
  completed: "已完成",
  failed: "失败",
};

export const Route = createFileRoute("/media/$jobId")({
  component: MediaDetail,
});

function MediaDetail() {
  const { jobId } = Route.useParams();
  const { data, isLoading } = useMediaJob(jobId);
  useMediaStream(jobId);

  if (isLoading || !data) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-8">
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  const active = data.status === "transcribing" || data.status === "analyzing";

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <Link
          to="/media"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          返回媒体分析
        </Link>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <h1 className="min-w-0 truncate text-xl font-semibold tracking-tight">{data.filename}</h1>
          <div className="flex items-center gap-2">
            {active && <LoaderCircle className="size-4 animate-spin text-primary" />}
            <Badge variant={data.status === "completed" ? "default" : "secondary"}>
              {STATUS_LABELS[data.status]}
            </Badge>
          </div>
        </div>

        {data.summary && (
          <div className="mt-4 rounded-lg border bg-card p-3">
            <p className="text-xs font-semibold text-muted-foreground">分析摘要</p>
            <p className="mt-1 text-sm">{data.summary}</p>
          </div>
        )}

        <div className="mt-6">
          <Tabs defaultValue="transcript">
            <TabsList>
              <TabsTrigger value="transcript">转写 ({data.segments.length})</TabsTrigger>
              <TabsTrigger value="analysis">事实与证据</TabsTrigger>
            </TabsList>
            <TabsContent value="transcript" className="mt-4">
              <TranscriptView segments={data.segments} />
            </TabsContent>
            <TabsContent value="analysis" className="mt-4">
              <MediaFacts facts={data.facts} evidence={data.evidence} segments={data.segments} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
