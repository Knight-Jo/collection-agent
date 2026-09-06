import { Download, ExternalLink, Star } from "lucide-react";
import type { Material } from "@/api/types";

function Stars({ rating }: { rating: number }) {
  return (
    <span
      className="inline-flex items-center gap-0.5 text-amber-500"
      role="img"
      aria-label={`${rating} 星`}
    >
      {Array.from({ length: rating }, (_, index) => (
        <Star key={index} className="size-3 fill-current" />
      ))}
    </span>
  );
}

export function MaterialsList({ materials }: { materials: Material[] }) {
  if (materials.length === 0) {
    return <p className="px-1 py-6 text-sm text-muted-foreground">暂无材料</p>;
  }

  return (
    <ul className="space-y-3">
      {materials.map((material) => (
        <li key={material.id} className="rounded-lg border bg-card p-3">
          <div className="flex items-start justify-between gap-2">
            <a
              href={material.url}
              target="_blank"
              rel="noreferrer noopener"
              className="group flex items-start gap-1 text-sm font-medium hover:text-primary"
            >
              <span className="line-clamp-2">{material.title}</span>
              <ExternalLink className="mt-0.5 size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
            </a>
            {material.download_url && (
              <a
                href={material.download_url}
                title="下载源文件"
                className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <Download className="size-3.5" />
                下载
              </a>
            )}
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <Stars rating={material.rating} />
            <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground">
              {material.source_type}
            </span>
          </div>
          <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">
            {material.description}
          </p>
        </li>
      ))}
    </ul>
  );
}
