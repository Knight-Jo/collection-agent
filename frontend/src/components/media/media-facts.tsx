import type { MediaEvidence, MediaFact, MediaSegment } from "@/api/types";
import { Badge } from "@/components/ui/badge";

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function MediaFacts({
  facts,
  evidence,
  segments,
}: {
  facts: MediaFact[];
  evidence: MediaEvidence[];
  segments: MediaSegment[];
}) {
  const segmentById = new Map(segments.map((segment) => [segment.id, segment]));

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-muted-foreground">提取事实</h3>
        <ul className="mt-2 space-y-2">
          {facts.map((fact) => {
            const segment = segmentById.get(fact.segment_id);
            return (
              <li key={fact.id} className="rounded-lg border bg-card p-3">
                <p className="text-sm">{fact.statement}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant={fact.status === "accepted" ? "default" : "secondary"}>
                    {fact.status === "accepted" ? "已采纳" : "待核验"}
                  </Badge>
                  {segment && (
                    <span className="font-mono text-xs text-muted-foreground">
                      {formatTime(segment.start)}–{formatTime(segment.end)}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
          {facts.length === 0 && (
            <p className="px-1 py-4 text-sm text-muted-foreground">正在分析事实…</p>
          )}
        </ul>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-muted-foreground">证据引用</h3>
        <ul className="mt-2 space-y-2">
          {evidence.map((item) => (
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
                <span className="font-mono text-xs text-muted-foreground">
                  {formatTime(item.start)}–{formatTime(item.end)}
                </span>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">“{item.quote}”</p>
            </li>
          ))}
          {evidence.length === 0 && (
            <p className="px-1 py-4 text-sm text-muted-foreground">正在抽取证据…</p>
          )}
        </ul>
      </section>
    </div>
  );
}
