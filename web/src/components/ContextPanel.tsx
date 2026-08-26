import { ExternalLink, FileText, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ReportVersion, ResearchRun, SearchPlanVersion } from "../types";
import type { ContextSelection } from "./ConversationPanel";

export function ContextPanel({
  selection,
  onClose,
  onSelect = () => undefined,
}: {
  selection: ContextSelection;
  onClose: () => void;
  onSelect?: (selection: ContextSelection) => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [plan, setPlan] = useState<SearchPlanVersion | null>(null);
  const [report, setReport] = useState<ReportVersion | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    closeButton.current?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  useEffect(() => {
    setRun(null);
    setPlan(null);
    setReport(null);
    setError("");
    const load = async () => {
      try {
        if (selection.kind === "run") setRun(await api.researchRun(selection.id));
        if (selection.kind === "search_plan_version") {
          setPlan(await api.searchPlanVersion(selection.id));
        }
        if (selection.kind === "report_version") {
          setReport(await api.reportVersion(selection.id));
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "详情加载失败");
      }
    };
    void load();
  }, [selection]);

  const citation = selection.kind === "citation" ? selection.value : null;
  return (
    <aside className="context-panel" role="dialog" aria-modal="true" aria-label="上下文详情">
      <header>
        <strong>上下文详情</strong>
        <button
          ref={closeButton}
          type="button"
          className="icon-button"
          aria-label="关闭详情"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </header>
      {error && <p className="form-error">{error}</p>}

      {citation && (
        <article className="context-content">
          <small>
            {citation.citation_kind === "verified_evidence" ? "已验证证据" : "材料线索"}
          </small>
          <h2>{citation.title}</h2>
          <blockquote>{citation.quote_text}</blockquote>
          <p>
            定位：第 {citation.line_start}–{citation.line_end} 行
          </p>
          <a href={citation.source_url} target="_blank" rel="noreferrer noopener">
            查看原始来源 <ExternalLink size={14} />
          </a>
        </article>
      )}

      {run && (
        <article className="context-content">
          <small>Research Run</small>
          <h2>{run.id}</h2>
          <dl>
            <div>
              <dt>状态</dt>
              <dd>{run.status}</dd>
            </div>
            <div>
              <dt>阶段</dt>
              <dd>{run.phase ?? "等待开始"}</dd>
            </div>
          </dl>
          {run.error && <p className="form-error">{run.error}</p>}
          {run.active_search_plan_version_id && (
            <button
              type="button"
              className="secondary-button"
              onClick={() =>
                onSelect({
                  kind: "search_plan_version",
                  id: run.active_search_plan_version_id ?? "",
                })
              }
            >
              <Search size={15} />
              查看 Search Plan
            </button>
          )}
        </article>
      )}

      {plan && (
        <article className="context-content">
          <small>版本化检索计划</small>
          <h2>Search Plan V{plan.sequence}</h2>
          <pre>{JSON.stringify(plan.plan, null, 2)}</pre>
        </article>
      )}

      {report && (
        <article className="context-content">
          <FileText size={20} />
          <small>报告版本</small>
          <h2>报告 V{report.version}</h2>
          <p>{report.status}</p>
          <p>基于研究状态 v{report.based_on_committed_state_version}</p>
          {report.based_on_checkpoint_id && <p>Checkpoint：{report.based_on_checkpoint_id}</p>}
          <code>{report.content_path}</code>
        </article>
      )}
    </aside>
  );
}
