import { Download } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Report } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const EXPORT_FORMATS = [
  { format: "markdown", label: "Markdown (.md)" },
  { format: "pdf", label: "PDF (.pdf)" },
  { format: "docx", label: "Word (.docx)" },
];

export function ReportView({
  report,
  conversationId,
}: {
  report: Report;
  conversationId?: string;
}) {
  return (
    <article className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <span className="text-sm font-medium">调研报告</span>
        <Badge variant={report.status === "published" ? "default" : "secondary"}>
          {report.status === "published" ? "已发布" : "草稿"}
        </Badge>
        <span className="ml-auto text-xs text-muted-foreground">V{report.version}</span>
        {conversationId && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="ml-2 h-7 gap-1 text-xs">
                <Download className="size-3.5" />
                下载
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {EXPORT_FORMATS.map((item) => (
                <DropdownMenuItem key={item.format} asChild>
                  <a
                    href={`/api/conversations/${conversationId}/report/export?format=${item.format}`}
                  >
                    {item.label}
                  </a>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
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
