import type { Material, TimelineEntry } from "@/api/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AgentTimeline } from "./agent-timeline";
import { MaterialsList } from "./materials-list";

export function WorkArea({
  materials,
  timeline,
  evidenceCount,
}: {
  materials: Material[];
  timeline: TimelineEntry[];
  evidenceCount: number;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b px-4 py-2.5 text-xs text-muted-foreground">
        <span>材料 {materials.length}</span>
        <span>·</span>
        <span>证据 {evidenceCount}</span>
      </div>
      <ScrollArea className="flex-1">
        <Tabs defaultValue="materials" className="px-4 py-3">
          <TabsList>
            <TabsTrigger value="materials">材料</TabsTrigger>
            <TabsTrigger value="trajectory">运行详情</TabsTrigger>
          </TabsList>
          <TabsContent value="materials" className="mt-4">
            <MaterialsList materials={materials} />
          </TabsContent>
          <TabsContent value="trajectory" className="mt-4">
            <AgentTimeline entries={timeline} />
          </TabsContent>
        </Tabs>
      </ScrollArea>
    </div>
  );
}
