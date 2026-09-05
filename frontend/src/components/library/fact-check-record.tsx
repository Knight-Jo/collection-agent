import type { FactCheck } from "@/api/types";
import { EvidenceTable } from "@/components/fact-check/evidence-table";
import { VerdictCard } from "@/components/fact-check/verdict-card";
import { AgentTimeline } from "@/components/research/agent-timeline";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function FactCheckRecord({ check }: { check: FactCheck }) {
  return (
    <div className="space-y-4">
      <VerdictCard factCheck={check} />

      {check.understanding && (
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">系统理解</p>
          <p className="mt-1 text-sm">{check.understanding}</p>
        </div>
      )}

      <Tabs defaultValue="evidence">
        <TabsList>
          <TabsTrigger value="evidence">正反证据 ({check.evidence.length})</TabsTrigger>
          <TabsTrigger value="trajectory">核验轨迹</TabsTrigger>
        </TabsList>
        <TabsContent value="evidence" className="mt-4">
          <EvidenceTable evidence={check.evidence} />
        </TabsContent>
        <TabsContent value="trajectory" className="mt-4">
          <AgentTimeline entries={check.timeline} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
