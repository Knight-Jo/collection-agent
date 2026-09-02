import { FileText, LoaderCircle, Search, Send } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ConversationProjection, MessageCitation, ResearchRun } from "../types";
import { RunStatusCard } from "./RunStatusCard";

const REFRESH_EVENTS = [
  "message.accepted",
  "action.proposed",
  "action.queued",
  "run.queued",
  "run.running",
  "run.stopping",
  "run.stopped",
  "run.succeeded",
  "run.failed",
  "checkpoint.committed",
  "report.created",
  "report.published",
];

export type ContextSelection =
  | { kind: "run"; id: string }
  | { kind: "search_plan_version"; id: string }
  | { kind: "citation"; value: MessageCitation }
  | { kind: "report_version"; id: string };

function clientMessageId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function ConversationPanel({
  conversationId,
  taskId,
  onOpenContext = () => undefined,
  onProjectionChange,
}: {
  conversationId?: string;
  taskId?: string;
  onOpenContext?: (selection: ContextSelection) => void;
  onProjectionChange?: (projection: ConversationProjection) => void;
}) {
  const [view, setView] = useState<ConversationProjection | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reportGenerating, setReportGenerating] = useState(false);
  const [streamingAnswer, setStreamingAnswer] = useState<{
    replyToId: string;
    content: string;
  } | null>(null);
  const [pendingMessage, setPendingMessage] = useState<{
    id: string;
    content: string;
    sending: boolean;
  } | null>(null);
  const reportRequestPending = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setView(
        conversationId
          ? await api.conversationById(conversationId)
          : await api.conversation(taskId ?? ""),
      );
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载会话失败");
    }
  }, [conversationId, taskId]);

  useEffect(() => {
    if (view) onProjectionChange?.(view);
  }, [onProjectionChange, view]);

  useEffect(() => {
    void refresh();
    if (typeof EventSource === "undefined") return;
    const eventPath = conversationId
      ? `/api/conversations/${conversationId}/events`
      : `/api/tasks/${taskId}/conversation/events`;
    const events = new EventSource(eventPath);
    for (const eventType of REFRESH_EVENTS) events.addEventListener(eventType, refresh);
    events.addEventListener("answer.started", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setStreamingAnswer({ replyToId: data.reply_to_id, content: "" });
    });
    events.addEventListener("answer.delta", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setStreamingAnswer((current) => ({
        replyToId: data.reply_to_id,
        content:
          current && current.replyToId === data.reply_to_id
            ? current.content + data.delta
            : data.delta,
      }));
    });
    const finishAnswer = async () => {
      await refresh();
      setPendingMessage(null);
      setStreamingAnswer(null);
    };
    events.addEventListener("answer.completed", () => void finishAnswer());
    events.addEventListener("answer.failed", () => void finishAnswer());
    events.addEventListener("run.progress", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      const phases: ResearchRun["phase"][] = [
        "planning",
        "collecting",
        "assessing",
        "checkpointing",
      ];
      if (!phases.includes(data.phase)) return;
      setView((current) =>
        current
          ? {
              ...current,
              runs: current.runs.map((run) =>
                run.id === data.run_id ? { ...run, phase: data.phase } : run,
              ),
            }
          : current,
      );
    });
    events.onerror = () => {
      setError("实时连接中断，正在重新同步完整会话。");
      setStreamingAnswer(null);
      void refresh();
    };
    return () => events.close();
  }, [conversationId, refresh, taskId]);

  const latestRun = view?.runs.at(-1);
  const activeRun =
    latestRun && ["queued", "running", "stopping"].includes(latestRun.status)
      ? latestRun
      : undefined;
  const failedRun =
    latestRun && ["failed", "interrupted"].includes(latestRun.status) ? latestRun : undefined;
  const attemptsByMessage = useMemo(
    () =>
      new Map(
        (view?.processing_attempts ?? []).map((attempt) => [attempt.user_message_id, attempt]),
      ),
    [view],
  );
  const reportIsCurrent = useMemo(
    () =>
      (view?.reports ?? []).some(
        (report) =>
          ["draft", "published"].includes(report.status) &&
          report.based_on_committed_state_version === view?.committed_state_version,
      ),
    [view],
  );
  const pendingIsPersisted = Boolean(
    pendingMessage && view?.messages.some((message) => message.id === pendingMessage.id),
  );

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

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    const targetConversationId = view?.conversation.id ?? conversationId;
    if (!targetConversationId) return;
    const optimisticId = clientMessageId();
    setInput("");
    setError("");
    setBusy(true);
    setPendingMessage({ id: optimisticId, content, sending: true });
    try {
      const submitted = conversationId
        ? await api.sendConversationMessage(targetConversationId, content, optimisticId)
        : await api.sendMessage(taskId ?? "", content, optimisticId);
      setPendingMessage({ id: submitted.id, content, sending: false });
      await refresh();
    } catch (cause) {
      setPendingMessage(null);
      setInput((current) => current || content);
      setError(cause instanceof Error ? cause.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  async function generateReport() {
    const task = view?.conversation.task_id;
    if (!task || reportRequestPending.current || reportIsCurrent) return;
    reportRequestPending.current = true;
    setReportGenerating(true);
    try {
      await mutate(() => api.createReportVersion(task));
    } finally {
      reportRequestPending.current = false;
      setReportGenerating(false);
    }
  }

  if (!view) return <p className="workbench-loading">正在加载会话…</p>;

  return (
    <section className="conversation-main" aria-label="Conversation Timeline">
      <header className="conversation-heading">
        <div>
          <small>{view.conversation.status === "intake" ? "需求确认" : "公开信息调研"}</small>
          <h1>{view.conversation.title}</h1>
        </div>
        <span>已提交 v{view.committed_state_version}</span>
      </header>

      <div className="message-list" aria-live="polite">
        {view.messages.length === 0 && (
          <div className="empty-state compact-empty">
            <h2>请描述你想调查的问题</h2>
            <p>可以直接给出主题，也可以先问“你能做什么？”。</p>
          </div>
        )}
        {view.messages.map((message) => (
          <article className={`message message-${message.role}`} key={message.id}>
            <header>{message.role === "user" ? "你" : "调研助手"}</header>
            <p>{message.content}</p>
            {attemptsByMessage.get(message.id)?.status === "failed" && (
              <footer className="message-processing-error">
                <span>{attemptsByMessage.get(message.id)?.error_detail ?? "消息处理失败"}</span>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => void mutate(() => api.retryMessage(message.id))}
                >
                  重试处理
                </button>
              </footer>
            )}
            {message.citations.length > 0 && (
              <footer className="citation-buttons">
                {message.citations.map((citation) => (
                  <button
                    type="button"
                    key={citation.id}
                    aria-label={`引用 ${citation.sequence}`}
                    onClick={() => onOpenContext({ kind: "citation", value: citation })}
                  >
                    [{citation.sequence}]
                  </button>
                ))}
              </footer>
            )}
          </article>
        ))}
        {pendingMessage && !pendingIsPersisted && (
          <article className="message message-user message-optimistic">
            <header>你</header>
            <p>{pendingMessage.content}</p>
            <footer>{pendingMessage.sending ? "正在发送…" : "已发送"}</footer>
          </article>
        )}
        {pendingMessage && !pendingMessage.sending && !streamingAnswer && (
          <article className="message message-assistant message-streaming">
            <header>调研助手</header>
            <p>正在分析已有材料…</p>
          </article>
        )}
        {streamingAnswer && (
          <article className="message message-assistant message-streaming">
            <header>调研助手 · 生成中</header>
            <p>{streamingAnswer.content || "正在生成回答…"}</p>
          </article>
        )}

        {activeRun && (
          <RunStatusCard
            run={activeRun}
            committedStateVersion={view.committed_state_version}
            busy={busy}
            onOpen={() => onOpenContext({ kind: "run", id: activeRun.id })}
            onStop={() => void mutate(() => api.stopResearchRun(activeRun.id))}
            onCancel={() => void mutate(() => api.cancelResearchRun(activeRun.id))}
          />
        )}

        {failedRun && (
          <article className="run-status-card" role="alert">
            <header className="run-status-card__header">
              <Search size={18} />
              <strong>调研未完成</strong>
            </header>
            <p>{failedRun.error ?? "运行意外中断，请重试。"}</p>
            <footer className="run-status-card__footer">
              <button
                type="button"
                className="text-button"
                onClick={() => onOpenContext({ kind: "run", id: failedRun.id })}
              >
                查看运行详情
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() => void mutate(() => api.retryResearchRun(failedRun.id))}
              >
                重试调研
              </button>
            </footer>
          </article>
        )}

        {view.actions.map((action) => (
          <article className="action-card" key={action.id}>
            <Search size={17} />
            <div className="report-timeline-card__body">
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
                  onClick={() => void mutate(() => api.confirmAction(action.id, clientMessageId()))}
                >
                  继续搜索
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={busy}
                  onClick={() => void mutate(() => api.rejectAction(action.id))}
                >
                  暂不搜索
                </button>
              </div>
            )}
          </article>
        ))}

        {view.reports.map((report) => (
          <article className="report-timeline-card" key={report.id}>
            <FileText size={18} />
            <div>
              <strong>
                报告 {report.status === "draft" ? "草稿" : "版本"} V{report.version}
              </strong>
              <p>
                基于{" "}
                {report.based_on_checkpoint_id ??
                  `研究状态 v${report.based_on_committed_state_version}`}
              </p>
            </div>
            <button
              type="button"
              className="secondary-button"
              onClick={() => onOpenContext({ kind: "report_version", id: report.id })}
            >
              查看
            </button>
            {report.status === "draft" && (
              <button
                type="button"
                className="primary-button"
                disabled={busy}
                aria-label={`发布 V${report.version}`}
                onClick={() => void mutate(() => api.publishReportVersion(report.id))}
              >
                发布
              </button>
            )}
          </article>
        ))}

        {view.conversation.task_id && !activeRun && view.report_ready && (
          <button
            type="button"
            className="secondary-button report-create-button"
            disabled={busy || reportGenerating || reportIsCurrent}
            onClick={() => void generateReport()}
          >
            {reportGenerating ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <FileText size={16} />
            )}
            {reportGenerating
              ? "正在生成报告…"
              : reportIsCurrent
                ? "报告已是最新"
                : view.reports.length > 0
                  ? "生成新版报告"
                  : "生成报告草稿"}
          </button>
        )}
      </div>

      <form
        className="conversation-input"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <textarea
          aria-label={taskId ? "继续提问" : "输入消息"}
          placeholder="输入问题、修改方向或明确要求继续搜索…"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send();
            }
          }}
          rows={3}
        />
        <button className="primary-button" type="submit" disabled={busy || !input.trim()}>
          <Send size={16} />
          发送
        </button>
      </form>
      {error && <p className="form-error">{error}</p>}
    </section>
  );
}
