import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ChevronRight, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { Verdict } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useCreateFactCheck, useFactChecks } from "@/hooks/use-fact-checks";

const VERDICT_LABELS: Record<Verdict, string> = {
  supported: "支持",
  mostly_supported: "基本支持",
  insufficient: "证据不足",
  disputed: "存在争议",
  mostly_refuted: "基本不支持",
  refuted: "错误",
};

export const Route = createFileRoute("/fact-check/")({
  component: FactCheckIndex,
});

function FactCheckIndex() {
  const navigate = useNavigate();
  const { data: checks, isLoading } = useFactChecks();
  const createFactCheck = useCreateFactCheck();
  const [claim, setClaim] = useState("");

  async function submit() {
    const value = claim.trim();
    if (!value || createFactCheck.isPending) return;
    const check = await createFactCheck.mutateAsync(value);
    await navigate({ to: "/fact-check/$checkId", params: { checkId: check.id } });
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-6 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">事实核验</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          输入一个断言，系统检索公开来源并给出支持/反驳证据与结论。
        </p>

        <div className="mt-6 flex flex-col items-stretch gap-2 rounded-lg border bg-card p-4">
          <Textarea
            value={claim}
            onChange={(event) => setClaim(event.target.value)}
            placeholder="例如：长电科技是全球第三大半导体封测厂商"
            rows={3}
          />
          <Button
            className="self-end"
            onClick={submit}
            disabled={!claim.trim() || createFactCheck.isPending}
          >
            <ShieldCheck />
            开始核验
          </Button>
        </div>

        <section className="mt-8">
          <h2 className="text-lg font-semibold">历史核验</h2>
          <div className="mt-3 space-y-3">
            {isLoading && (
              <div className="space-y-3">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            )}
            {checks?.map((check) => (
              <Link
                key={check.id}
                to="/library"
                search={{ dim: "fact-check", id: check.id }}
                className="block"
              >
                <Card className="transition-shadow hover:shadow-sm">
                  <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
                    <div className="min-w-0">
                      <CardTitle className="truncate text-base">{check.claim}</CardTitle>
                      <CardDescription className="mt-1">
                        {new Date(check.created_at).toLocaleString("zh-CN")}
                      </CardDescription>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {check.verdict && (
                        <Badge
                          variant={
                            check.verdict === "supported" || check.verdict === "mostly_supported"
                              ? "default"
                              : check.verdict === "refuted" || check.verdict === "mostly_refuted"
                                ? "secondary"
                                : "outline"
                          }
                        >
                          {VERDICT_LABELS[check.verdict]}
                        </Badge>
                      )}
                      <ChevronRight className="size-4 text-muted-foreground" />
                    </div>
                  </CardHeader>
                </Card>
              </Link>
            ))}
            {!isLoading && checks?.length === 0 && (
              <p className="text-sm text-muted-foreground">暂无历史核验记录</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
