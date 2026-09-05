import type { MediaSegment } from "@/api/types";

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function TranscriptView({ segments }: { segments: MediaSegment[] }) {
  if (segments.length === 0) {
    return <p className="px-1 py-6 text-sm text-muted-foreground">正在转写…</p>;
  }

  return (
    <ol className="space-y-3">
      {segments.map((segment) => (
        <li key={segment.id} className="flex gap-3 rounded-lg border bg-card p-3">
          <span className="shrink-0 font-mono text-xs text-muted-foreground">
            {formatTime(segment.start)}–{formatTime(segment.end)}
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium text-primary">{segment.speaker}</p>
            <p className="mt-0.5 text-sm leading-relaxed">{segment.text}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
