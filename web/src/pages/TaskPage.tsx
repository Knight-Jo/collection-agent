import { useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, FileText, Quote } from "lucide-react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { ReportView } from "../components/ReportView";
import { StageStepper } from "../components/StageStepper";
import type { Artifact, TaskDetail } from "../types";

export function TaskPage() {
  const { taskId = "" } = useParams();
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [tab, setTab] = useState<"evidence" | "report">("evidence");
  const [error, setError] = useState("");
  useEffect(() => { api.task(taskId).then(setDetail).catch((cause) => setError(cause.message)); }, [taskId]);

  async function showReport() {
    setTab("report");
    if (!artifact) api.artifact(taskId, "assessment").then(setArtifact).catch((cause) => setError(cause.message));
  }
  if (error && !detail) return <main className="page"><p className="form-error">{error}</p></main>;
  if (!detail) return <main className="page"><p className="muted">正在加载研究…</p></main>;
  const evidenceCount = detail.questions.flatMap((q) => q.facts).reduce((sum, fact) => sum + fact.evidence.length, 0);
  return <main className="page"><div className="task-title"><div><div className="eyebrow">RESEARCH DOSSIER</div><h1>{detail.task.topic}</h1><p>{detail.questions.length} 个关键问题 · {evidenceCount} 条证据 · 更新于 {new Date(detail.task.updated_at).toLocaleString("zh-CN")}</p></div><div className="score-card"><span>缺口分</span><strong>{detail.coverage?.gap_score ?? "—"}</strong><small>{detail.coverage?.level?.replace("_", " ") ?? "待评估"}</small></div></div><StageStepper stage={detail.task.stage} /><nav className="tabs" aria-label="研究内容"><button data-active={tab === "evidence"} onClick={() => setTab("evidence")}><Quote size={17} />证据链</button><button data-active={tab === "report"} onClick={showReport}><FileText size={17} />研判报告</button></nav>{tab === "report" ? artifact ? <ReportView markdown={artifact.content} /> : <div className="empty-state"><FileText /><h3>报告尚未生成</h3><p>{error || "任务完成后，研判报告将在此显示。"}</p></div> : <div className="question-list">{detail.questions.map((question, index) => <section className="question-panel" key={question.id}><header><span>Q{index + 1}</span><div><h2>{question.text}</h2><p>{question.facts.length} 项事实 · {question.coverage?.status ?? "待评估"}</p></div></header>{question.facts.length ? question.facts.map((fact) => <article className="fact-card" key={fact.id}><div className="fact-heading"><span className={`coverage-dot ${fact.coverage?.status ?? "gap"}`} /><h3>{fact.statement}</h3></div>{fact.evidence.map((evidence) => <blockquote key={evidence.id} data-relation={evidence.relation}><Quote size={17} /><div><p>{evidence.quote}</p><footer><a href={evidence.document.final_url} target="_blank" rel="noreferrer noopener">{evidence.document.title || evidence.document.source_group}<ExternalLink size={13} /></a><span>第 {evidence.line_start}–{evidence.line_end} 行</span><span className={`verdict verdict-${evidence.review?.verdict ?? "pending"}`}>{evidence.review?.verdict ?? "待审核"}</span></footer>{evidence.document.injection_warnings.length > 0 && <small className="warning"><AlertTriangle size={13} />文档含可疑指令，已按不可信内容处理</small>}</div></blockquote>)}</article>) : <p className="muted inset">尚未形成可核验事实。</p>}</section>)}</div>}</main>;
}
