import { createFileRoute, Link } from "@tanstack/react-router";
import { ChevronRight, Clapperboard } from "lucide-react";
import type { MediaJobStatus } from "@/api/types";
import { MediaUpload } from "@/components/media/media-upload";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useMediaJobs } from "@/hooks/use-media";

const STATUS_LABELS: Record<MediaJobStatus, string> = {
  transcribing: "转写中",
  analyzing: "分析中",
  completed: "已完成",
  failed: "失败",
};

export const Route = createFileRoute("/media/")({
  component: MediaIndex,
});

function MediaIndex() {
  const { data: jobs, isLoading } = useMediaJobs();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <div className="flex items-center gap-2">
          <Clapperboard className="size-6 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">媒体分析</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          上传音视频，转写内容并提取其中的事实与证据。
        </p>

        <div className="mt-6">
          <MediaUpload />
        </div>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">历史任务</h2>
          <div className="mt-3 space-y-3">
            {isLoading && (
              <div className="space-y-3">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            )}
            {jobs?.map((job) => (
              <Link key={job.id} to="/media/$jobId" params={{ jobId: job.id }} className="block">
                <div className="flex items-center justify-between gap-4 rounded-lg border bg-card p-3 transition-shadow hover:shadow-sm">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{job.filename}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString("zh-CN")} ·{" "}
                      {job.kind === "video" ? "视频" : "音频"}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge
                      variant={job.status === "completed" ? "default" : "secondary"}
                      className={
                        job.status === "failed" ? "bg-destructive/10 text-destructive" : undefined
                      }
                    >
                      {STATUS_LABELS[job.status]}
                    </Badge>
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </div>
                </div>
              </Link>
            ))}
            {!isLoading && jobs?.length === 0 && (
              <p className="text-sm text-muted-foreground">暂无媒体分析任务</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
