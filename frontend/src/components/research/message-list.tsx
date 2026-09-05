import type { Message } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function MessageList({ messages, streaming }: { messages: Message[]; streaming: string }) {
  return (
    <div className="space-y-4">
      {messages.length === 0 && !streaming && (
        <div className="py-16 text-center text-sm text-muted-foreground">
          <p className="text-base font-medium text-foreground">从一个问题开始调研</p>
          <p className="mt-1">可以先询问系统能力，也可以直接描述需要调查的主题、范围和产出。</p>
        </div>
      )}
      {messages.map((message) => (
        <div
          key={message.id}
          className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}
        >
          <div
            className={cn(
              "max-w-[85%] rounded-2xl px-4 py-3 text-sm",
              message.role === "user" ? "bg-primary text-primary-foreground" : "bg-card border",
            )}
          >
            <p className="mb-1 text-[10px] font-semibold opacity-60">
              {message.role === "user" ? "你" : "调研助手"}
            </p>
            <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
            {message.citations.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {message.citations.map((citation) => (
                  <Button
                    key={citation.id}
                    variant="outline"
                    size="sm"
                    className="h-6 rounded-md px-2 text-[11px]"
                  >
                    [{citation.sequence}] {citation.title}
                  </Button>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
      {streaming && (
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-2xl border bg-card px-4 py-3 text-sm">
            <p className="mb-1 text-[10px] font-semibold opacity-60">调研助手 · 生成中</p>
            <p className="whitespace-pre-wrap leading-relaxed">{streaming}</p>
          </div>
        </div>
      )}
    </div>
  );
}
