import { Brain, CheckCircle2, Eye, GitBranch, PlayCircle, RefreshCw, Sparkles } from "lucide-react";
import type { RunEvent, TrajectoryEnvelope } from "../types";

const reasonLabels: Record<string, string> = {
  LOW_COVERAGE: "覆盖不足",
  MISSING_PRIMARY_SOURCE: "缺一手来源",
  LOW_SOURCE_DIVERSITY: "来源单一",
  EVIDENCE_GAIN_TOO_LOW: "证据增益低",
  QUERY_BUDGET_EXHAUSTED: "预算耗尽",
  SEARCH_RESULT_NOT_MATERIALIZED: "检索未落地",
  SOURCE_CONTENT_NOT_ACQUIRED: "正文未获取",
  CLAIM_NOT_VERIFIED: "声明未核验",
  EVIDENCE_NOT_VERIFIED: "证据未审核",
  CONFLICT_UNRESOLVED: "矛盾未消解",
};

const originLabel: Record<string, string> = {
  model: "模型",
  deterministic: "确定性",
  policy: "规则",
  human: "人工",
  system: "系统",
  tool: "工具",
};

const sourceLabel: Record<string, string> = {
  rule: "规则",
  derived: "推断",
  explicit: "显式",
};

function envelope(event: RunEvent): TrajectoryEnvelope | null {
  if (!event.type.startsWith("trajectory.")) return null;
  const data = event.data as Partial<TrajectoryEnvelope>;
  return data && typeof data.event_type === "string" ? (data as TrajectoryEnvelope) : null;
}

function stateSnapshot(snapshot: Record<string, unknown> | undefined): string {
  if (!snapshot || !Object.keys(snapshot).length) return "";
  const parts = Object.entries(snapshot)
    .filter(([, value]) => value !== null)
    .slice(0, 4)
    .map(([key, value]) => `${key}=${value}`);
  return parts.join(" · ");
}

function deltaSummary(payload: Record<string, unknown>): string {
  const delta = payload.delta as Record<string, { before?: unknown; after?: unknown }> | undefined;
  if (!delta || !Object.keys(delta).length) return "";
  return Object.entries(delta)
    .map(([key, change]) => `${key}: ${change.before} → ${change.after}`)
    .join(" · ");
}

function EventRow({ env }: { env: TrajectoryEnvelope }) {
  const payload = env.payload;
  switch (env.event_type) {
    case "model_call": {
      const p = payload as {
        request_index?: number;
        input_tokens?: number | null;
        output_tokens?: number | null;
        latency_ms?: number | null;
        finish_reason?: string | null;
      };
      return (
        <li className="dt-model">
          <Brain size={16} />
          <div>
            <strong>第 {p.request_index} 次模型调用</strong>
            <p>
              in={p.input_tokens ?? "—"} out={p.output_tokens ?? "—"} tokens ·{" "}
              {p.latency_ms != null ? `${p.latency_ms}ms` : "—"} · {p.finish_reason ?? "—"}
            </p>
          </div>
        </li>
      );
    }
    case "decision": {
      const p = payload as {
        decision?: string;
        reason_codes?: string[];
        reason_source?: string;
        reason_summary?: string;
        state_snapshot?: Record<string, unknown>;
      };
      const snapshot = stateSnapshot(p.state_snapshot);
      const reasonCodes = p.reason_codes ?? [];
      return (
        <li className="dt-decision">
          <GitBranch size={16} />
          <div>
            <strong>
              决策：{p.decision}
              <span className="dt-origin">{originLabel[env.origin] ?? env.origin}</span>
              <span className="dt-source">
                {sourceLabel[p.reason_source ?? ""] ?? p.reason_source}
              </span>
            </strong>
            {reasonCodes.length > 0 && (
              <p className="dt-reasons">
                {reasonCodes.map((code) => (
                  <span className="dt-reason" key={code}>
                    {reasonLabels[code] ?? code}
                  </span>
                ))}
              </p>
            )}
            {p.reason_summary && <p className="dt-summary">{p.reason_summary}</p>}
            {snapshot && <p className="dt-snapshot">{snapshot}</p>}
          </div>
        </li>
      );
    }
    case "action": {
      const p = payload as { tool?: string };
      return (
        <li className="dt-action">
          <Sparkles size={16} />
          <div>
            <strong>行动：{p.tool}</strong>
          </div>
        </li>
      );
    }
    case "observation": {
      const p = payload as { tool?: string; result?: Record<string, unknown> };
      return (
        <li className="dt-observation">
          <Eye size={16} />
          <div>
            <strong>观察：{p.tool}</strong>
          </div>
        </li>
      );
    }
    case "state_updated": {
      const p = payload as {
        state_scope?: string;
        state_id?: string | null;
        delta?: Record<string, unknown>;
      };
      const delta = deltaSummary(payload);
      return (
        <li className="dt-state">
          <RefreshCw size={16} />
          <div>
            <strong>状态更新：{p.state_scope}</strong>
            {delta && <p className="dt-summary">{delta}</p>}
          </div>
        </li>
      );
    }
    case "run_started":
      return (
        <li className="dt-run">
          <PlayCircle size={16} />
          <div>
            <strong>运行开始</strong>
          </div>
        </li>
      );
    case "run_finished":
      return (
        <li className="dt-run">
          <CheckCircle2 size={16} />
          <div>
            <strong>运行结束</strong>
          </div>
        </li>
      );
    default:
      return null;
  }
}

export function DecisionTrace({ events }: { events: RunEvent[] }) {
  const trajectory = events.map(envelope).filter((env): env is TrajectoryEnvelope => env !== null);

  if (!trajectory.length) {
    return <p className="muted">暂无决策轨迹。</p>;
  }

  const steps = new Map<number | null, TrajectoryEnvelope[]>();
  for (const env of trajectory) {
    const list = steps.get(env.step_id) ?? [];
    list.push(env);
    steps.set(env.step_id, list);
  }

  return (
    <div className="decision-trace">
      {[...steps.entries()].map(([stepId, list]) => (
        <section className="dt-step" key={stepId ?? "root"}>
          <header>
            <span className="dt-step-id">Step {stepId ?? "—"}</span>
            <span className="dt-count">{list.length} 个事件</span>
          </header>
          <ol>
            {list.map((env) => (
              <EventRow env={env} key={env.event_id} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
