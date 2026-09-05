import { LoaderCircle } from "lucide-react";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAgentStream } from "@/hooks/use-agent-stream";
import { useConversation, useSendMessage } from "@/hooks/use-conversation";
import { Composer } from "./composer";
import { MessageList } from "./message-list";
import { ResearchStructure } from "./research-structure";
import { RunStatus } from "./run-status";
import { WorkArea } from "./work-area";

export function Workspace({ conversationId }: { conversationId: string }) {
  const { data, isLoading } = useConversation(conversationId);
  const send = useSendMessage(conversationId);
  const { streaming } = useAgentStream(conversationId);

  if (isLoading || !data) {
    return (
      <div className="grid h-full place-items-center text-muted-foreground">
        <LoaderCircle className="size-6 animate-spin" />
      </div>
    );
  }

  const busy =
    streaming !== "" ||
    (data.conversation.run_status !== null &&
      ["queued", "running", "stopping"].includes(data.conversation.run_status));
  const evidenceCount = data.questions.reduce((sum, question) => sum + question.evidence_count, 0);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] text-muted-foreground">
            {data.conversation.status === "intake" ? "需求确认" : "公开信息调研"}
          </p>
          <h1 className="truncate text-base font-semibold">{data.conversation.title}</h1>
        </div>
        <RunStatus run={data.run} />
      </header>

      <ResizablePanelGroup orientation="horizontal" className="flex-1">
        <ResizablePanel defaultSize={24} minSize={18}>
          <ScrollArea className="h-full">
            <ResearchStructure questions={data.questions} gaps={data.gaps} />
          </ScrollArea>
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={38} minSize={26}>
          <WorkArea
            materials={data.materials}
            timeline={data.timeline}
            evidenceCount={evidenceCount}
          />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel defaultSize={38} minSize={26}>
          <div className="flex h-full flex-col">
            <ScrollArea className="flex-1">
              <div className="px-4 py-4">
                <MessageList messages={data.messages} streaming={streaming} />
              </div>
            </ScrollArea>
            <div className="px-4 pb-4">
              <Composer busy={busy} onSubmit={(content) => send.mutate(content)} />
            </div>
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
