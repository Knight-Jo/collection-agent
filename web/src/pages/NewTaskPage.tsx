import { FormEvent, useEffect, useState } from "react";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Run, RunInput } from "../types";

export function NewTaskPage({ createRun }: { createRun: (input: RunInput) => Promise<Run> | Run | void }) {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [objective, setObjective] = useState("");
  const [questions, setQuestions] = useState<string[]>([]);
  const [timeRange, setTimeRange] = useState("");
  const [geography, setGeography] = useState("");
  const [languages, setLanguages] = useState("");
  const [reportDepth, setReportDepth] = useState<RunInput["report_depth"]>("standard");
  const [deepCrawl, setDeepCrawl] = useState<boolean | null>(null);
  const [systemReady, setSystemReady] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.system()
      .then((system) => setDeepCrawl((choice) => choice ?? system.crawl.default_enabled))
      .catch(() => undefined)
      .finally(() => setSystemReady(true));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return setError("请输入研究主题");
    if (!systemReady) return;
    setSubmitting(true);
    setError("");
    try {
      const split = (value: string) => value.split(/[,，]/).map((item) => item.trim()).filter(Boolean);
      const run = await createRun({
        topic: topic.trim(),
        objective: objective.trim(),
        questions: questions.map((item) => item.trim()).filter(Boolean),
        scope: { time_range: timeRange.trim(), geography: split(geography), languages: split(languages) },
        report_depth: reportDepth,
        deep_crawl: deepCrawl,
        criteria: {
          min_independent_sources: 2,
          min_high_quality_sources: 1,
          recency_days: 90,
          require_recency: false,
        },
      });
      if (run?.run_id) navigate(`/runs/${run.run_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建任务失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page narrow-page">
      <div className="eyebrow">NEW RESEARCH</div>
      <h1>开始一项公开信息调研</h1>
      <p className="lead">输入主题即可开始；智能体会制定问题、检索公开来源并生成结构化调研报告。</p>
      <form className="panel form-panel" onSubmit={submit}>
        <label>研究主题<input aria-label="研究主题" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：量子计算产业发展情况" autoFocus /></label>
        <label>调研目标 <span className="field-hint">可选</span><input aria-label="调研目标" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="例如：了解产业现状、政策与主要参与者" /></label>
        <fieldset>
          <legend>关键问题 <span>可选，最多 6 个；留空时由智能体制定</span></legend>
          {questions.map((question, index) => (
            <div className="question-row" key={index}>
              <span>{index + 1}</span>
              <input aria-label={`关键问题 ${index + 1}`} value={question} onChange={(event) => setQuestions((items) => items.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} placeholder="输入必须回答的具体问题" />
              <button className="icon-button" type="button" aria-label={`删除问题 ${index + 1}`} onClick={() => setQuestions((items) => items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={17} /></button>
            </div>
          ))}
          {questions.length < 6 && <button className="text-button" type="button" onClick={() => setQuestions((items) => [...items, ""])}><Plus size={17} />添加关键问题</button>}
        </fieldset>
        <details className="advanced-options">
          <summary>高级选项</summary>
          <div className="advanced-grid">
            <label>时间范围<input aria-label="时间范围" value={timeRange} onChange={(event) => setTimeRange(event.target.value)} placeholder="例如：2024-2026" /></label>
            <label>地区<input aria-label="地区" value={geography} onChange={(event) => setGeography(event.target.value)} placeholder="多个地区用逗号分隔" /></label>
            <label>语言<input aria-label="语言" value={languages} onChange={(event) => setLanguages(event.target.value)} placeholder="例如：zh-CN, en" /></label>
            <label>报告深度<select aria-label="报告深度" value={reportDepth} onChange={(event) => setReportDepth(event.target.value as RunInput["report_depth"])}><option value="brief">简报</option><option value="standard">标准</option><option value="deep">深度</option></select></label>
          </div>
          <label className="crawl-toggle"><input type="checkbox" aria-label="启用深度抓取" checked={deepCrawl ?? false} onChange={(event) => setDeepCrawl(event.target.checked)} />启用深度抓取<span>递归收集公开关联页面和多媒体附件。</span></label>
        </details>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-footer"><p>不同类型的信息采用相应核验标准；无法确认的内容会在报告中明确披露。</p><button className="primary-button" disabled={submitting || !systemReady}>{submitting ? "正在创建…" : "开始研究"}<ArrowRight size={18} /></button></div>
      </form>
    </main>
  );
}
