import type { FactCheck } from "@/api/types";
import { EvidenceTable } from "@/components/fact-check/evidence-table";
import { FactCheckSteps } from "@/components/fact-check/fact-check-steps";
import { VerdictCard } from "@/components/fact-check/verdict-card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function FactCheckRecord({ check }: { check: FactCheck }) {
  return (
    <div className="space-y-4">
      {check.checkability === "not_checkable" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
          <p className="font-medium">该断言无法核验</p>
          {check.checkability_reason && (
            <p className="mt-1 text-xs">{check.checkability_reason}</p>
          )}
        </div>
      )}

      <VerdictCard factCheck={check} />

      {check.understanding && (
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">系统理解</p>
          <p className="mt-1 text-sm">{check.understanding}</p>
        </div>
      )}

      {check.questions.length > 0 && (
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">核验问题</p>
          <ul className="mt-1 space-y-1">
            {check.questions.map((question, index) => (
              <li key={question} className="flex items-start gap-2 text-sm">
                <span className="mt-0.5 text-primary">›</span>
                {question}
                {index === 0 && (
                  <Badge variant="secondary" className="ml-1 shrink-0">
                    主问题
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {check.rationale && (
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">公开依据</p>
          <p className="mt-1 text-sm">{check.rationale}</p>
        </div>
      )}

      {check.limitations.length > 0 && (
        <div className="rounded-lg border bg-card p-3">
          <p className="text-xs font-semibold text-muted-foreground">局限与不确定性</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {check.limitations.map((limitation) => (
              <li key={limitation} className="text-sm text-muted-foreground">
                {limitation}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Tabs defaultValue="evidence">
        <TabsList>
          <TabsTrigger value="evidence">正反证据 ({check.evidence.length})</TabsTrigger>
          <TabsTrigger value="trajectory">核验轨迹 ({check.timeline.length})</TabsTrigger>
        </TabsList>
        <TabsContent value="evidence" className="mt-4">
          <EvidenceTable evidence={check.evidence} />
        </TabsContent>
        <TabsContent value="trajectory" className="mt-4">
          <FactCheckSteps steps={check.timeline} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
