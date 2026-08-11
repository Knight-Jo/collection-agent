import { FormEvent, useEffect, useState } from "react";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Run, RunInput } from "../types";

export function NewTaskPage({ createRun }: { createRun: (input: RunInput) => Promise<Run> | Run | void }) {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [questions, setQuestions] = useState(["", ""]);
  const [deepCrawl, setDeepCrawl] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.system().then((system) => setDeepCrawl((choice) => choice ?? system.crawl.default_enabled)).catch(() => setDeepCrawl((choice) => choice ?? false));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleanQuestions = questions.map((item) => item.trim()).filter(Boolean);
    if (!topic.trim()) return setError("请输入研究主题");
    if (cleanQuestions.length < 2) return setError("请至少填写两个关键问题");
    if (deepCrawl === null) return;
    setSubmitting(true);
    setError("");
    try {
      const run = await createRun({
        topic: topic.trim(),
        questions: cleanQuestions,
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
      <h1>开始一项可信研究</h1>
      <p className="lead">明确主题与关键问题，智能体将自动检索、留存原文、审核证据并生成可追溯报告。</p>
      <form className="panel form-panel" onSubmit={submit}>
        <label>研究主题<input aria-label="研究主题" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="例如：2026 年低空经济投资进展" autoFocus /></label>
        <fieldset>
          <legend>关键问题 <span>至少 2 个，最多 6 个</span></legend>
          {questions.map((question, index) => (
            <div className="question-row" key={index}>
              <span>{index + 1}</span>
              <input aria-label={`关键问题 ${index + 1}`} value={question} onChange={(e) => setQuestions((items) => items.map((item, i) => i === index ? e.target.value : item))} placeholder="输入需要回答的具体问题" />
              {questions.length > 2 && <button className="icon-button" type="button" aria-label={`删除问题 ${index + 1}`} onClick={() => setQuestions((items) => items.filter((_, i) => i !== index))}><Trash2 size={17} /></button>}
            </div>
          ))}
          {questions.length < 6 && <button className="text-button" type="button" onClick={() => setQuestions((items) => [...items, ""])}><Plus size={17} />添加问题</button>}
        </fieldset>
        <label className="crawl-toggle"><input type="checkbox" aria-label="启用深度抓取" checked={deepCrawl ?? false} onChange={(event) => setDeepCrawl(event.target.checked)} />启用深度抓取<span>递归抓取可访问的关联页面和附件。</span></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="form-footer"><p>默认要求每项事实至少有 2 个独立来源，其中 1 个为高质量来源。</p><button className="primary-button" disabled={submitting || deepCrawl === null}>{submitting ? "正在创建…" : "开始研究"}<ArrowRight size={18} /></button></div>
      </form>
    </main>
  );
}
