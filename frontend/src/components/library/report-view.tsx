import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Report } from "@/api/types";
import { Badge } from "@/components/ui/badge";

export function ReportView({ report }: { report: Report }) {
  return (
    <article className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <span className="text-sm font-medium">调研报告</span>
        <Badge variant={report.status === "published" ? "default" : "secondary"}>
          {report.status === "published" ? "已发布" : "草稿"}
        </Badge>
        <span className="ml-auto text-xs text-muted-foreground">V{report.version}</span>
      </div>
      <div className="prose prose-sm max-w-none px-6 py-4">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ children, ...props }) => (
              <a {...props} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            ),
          }}
        >
          {report.content}
        </ReactMarkdown>
      </div>
    </article>
  );
}
