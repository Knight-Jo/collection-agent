import { useNavigate } from "@tanstack/react-router";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useCreateMediaJob } from "@/hooks/use-media";

export function MediaUpload() {
  const navigate = useNavigate();
  const createJob = useCreateMediaJob();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  async function submit(file: File) {
    if (!file.type.startsWith("audio/") && !file.type.startsWith("video/")) {
      setError("仅支持音频或视频文件");
      return;
    }
    setError("");
    const job = await createJob.mutateAsync({ file });
    await navigate({ to: "/media/$jobId", params: { jobId: job.id } });
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (file) void submit(file);
        }}
        className={`flex w-full cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"
        }`}
      >
        <Upload className="size-6 text-primary" />
        <p className="mt-2 text-sm font-medium">拖拽音视频文件到此处，或点击选择</p>
        <p className="mt-1 text-xs text-muted-foreground">
          支持 mp3 / wav / mp4 / webm 等，转写后提取情报
        </p>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="audio/*,video/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void submit(file);
          event.target.value = "";
        }}
      />
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      {createJob.isPending && <p className="mt-2 text-sm text-muted-foreground">正在上传…</p>}
    </div>
  );
}
