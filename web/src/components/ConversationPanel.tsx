import { ExternalLink, FileText, Quote, Search, Send, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ConversationProjection, MessageCitation } from "../types";

const EVENT_TYPES = [
  "message.accepted",
  "answer.completed",
  "action.proposed",
  "action.queued",
  "run.started",
  "run.completed",
  "run.failed",
  "report.draft_created",
  "report.published",
];

function clientMessageId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function ConversationPanel({ taskId }: { taskId: string }) {
  const [view, setView] = useState<ConversationProjection | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<MessageCitation | null>(null);

  const refresh = useCallback(
    () =>
      api
        .conversation(taskId)
        .then(setView)
        .catch((cause) => setError(cause.message)),
    [taskId],
  );

  useEffect(() => {
    void refresh();
    if (typeof EventSource === "undefined") return;
    const events = new EventSource(`/api/tasks/${taskId}/conversation/events`);
    for (const eventType of EVENT_TYPES) events.addEventListener(eventType, refresh);
    events.onerror = () => setError("实时连接已断开，浏览器正在重连。");
    return () => events.close();
  }, [refresh, taskId]);

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.sendMessage(taskId, content, clientMessageId());
      setInput("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  if (!view) return <p className="muted">正在加载任务对话…</p>;

  const activeRun = [...view.runs]
    .reverse()
    .find((run) => run.status === "queued" || run.status === "running");

  return (
    <section className="conversation-layout" aria-label="任务对话">
      <div className="conversation-main">
        <div className="conversation-status">
          <span>研究状态 v{view.committed_state_version}</span>
          <span>{view.messages.length} 条消息</span>
          {activeRun && <strong>{activeRun.phase ?? activeRun.status}</strong>}
        </div>
        <div className="message-list" aria-live="polite">
          {view.messages.length === 0 && (
            <div className="empty-state compact-empty">
              <h3>询问当前任务材料</h3>
              <p>普通问题只读取已收集材料；明确说“继续搜索”才会启动续研。</p>
            </div>
          )}
          {view.messages.map((message) => (
            <article className={`message message-${message.role}`} key={message.id}>
              <header>{message.role === "user" ? "你" : "调研助手"}</header>
              <p>{message.content}</p>
              {message.status === "failed" && <small className="warning">{message.error}</small>}
              {message.citations.length > 0 && (
                <footer className="citation-buttons">
                  {message.citations.map((citation) => (
                    <button
                      type="button"
                      key={citation.id}
                      aria-label={`引用 ${citation.sequence}`}
                      onClick={() => setSelectedCitation(citation)}
                    >
                      [{citation.sequence}]
                    </button>
                  ))}
                </footer>
              )}
            </article>
          ))}
          {view.messages.some(
            (message) =>
              message.role === "user" &&
              (message.status === "accepted" || message.status === "processing"),
          ) && <p className="message-pending">正在基于当前材料回答…</p>}
        </div>

        {view.actions.map((action) => (
          <div className="action-card" key={action.id}>
            <Search size={17} />
            <div>
              <strong>
                {action.action_type === "continue_research" ? "建议继续搜索" : action.action_type}
              </strong>
              <p>{JSON.stringify(action.immutable_payload)}</p>
            </div>
            {action.status === "proposed" && (
              <div className="action-buttons">
                <button
                  className="primary-button"
                  type="button"
                  disabled={busy}
                  onClick={() => mutate(() => api.confirmAction(action.id, clientMessageId()))}
                >
                  继续搜索
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={busy}
                  onClick={() => mutate(() => api.rejectAction(action.id))}
                >
                  暂不搜索
                </button>
              </div>
            )}
            {(action.status === "queued" || action.status === "executing") && (
              <button
                className="secondary-button"
                type="button"
                onClick={() => mutate(() => api.cancelAction(action.id))}
              >
                取消
              </button>
            )}
          </div>
        ))}

        <form
          className="conversation-input"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <textarea
            aria-label="继续提问"
            placeholder="询问已有材料，或明确要求继续搜索某个方向…"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            rows={3}
          />
          <button className="primary-button" type="submit" disabled={busy || !input.trim()}>
            <Send size={16} />
            发送
          </button>
        </form>
        {error && <p className="form-error">{error}</p>}
      </div>

      <aside className="conversation-side">
        {selectedCitation ? (
          <article className="citation-card">
            <button
              type="button"
              className="icon-button citation-close"
              aria-label="关闭引用"
              onClick={() => setSelectedCitation(null)}
            >
              <X size={16} />
            </button>
            <Quote size={19} />
            <strong>{selectedCitation.title}</strong>
            <p>{selectedCitation.quote_text}</p>
            <small>
              第 {selectedCitation.line_start}–{selectedCitation.line_end} 行 ·{" "}
              {selectedCitation.citation_kind === "verified_evidence" ? "已验证证据" : "材料线索"}
            </small>
            <a href={selectedCitation.source_url} target="_blank" rel="noreferrer noopener">
              查看原始来源 <ExternalLink size={13} />
            </a>
          </article>
        ) : (
          <div className="panel report-versions">
            <header>
              <FileText size={18} />
              <strong>报告版本</strong>
            </header>
            {view.reports.length === 0 && <p className="muted">尚无版本化报告。</p>}
            {view.reports.map((report) => (
              <div className="report-version" key={report.id}>
                <span>V{report.version}</span>
                <strong>{report.status}</strong>
                {report.status === "draft" && (
                  <button
                    type="button"
                    onClick={() => mutate(() => api.publishReportVersion(report.id))}
                  >
                    发布
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => mutate(() => api.createReportVersion(taskId))}
            >
              生成新草稿
            </button>
          </div>
        )}
      </aside>
    </section>
  );
}
