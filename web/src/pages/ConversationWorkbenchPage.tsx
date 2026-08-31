import { ArchiveRestore, MessageSquarePlus, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ContextPanel } from "../components/ContextPanel";
import { type ContextSelection, ConversationPanel } from "../components/ConversationPanel";
import { RUN_PHASE_LABELS } from "../components/RunStatusCard";
import type { Conversation, ConversationProjection } from "../types";

export function ConversationWorkbenchPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [context, setContext] = useState<ContextSelection | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [changingConversation, setChangingConversation] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setConversations(await api.conversations(showArchived));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载历史会话失败");
    }
  }, [showArchived]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setContext(null);
  }, [conversationId]);

  async function createConversation() {
    try {
      const created = await api.createConversation();
      await refresh();
      navigate(`/conversations/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建对话失败");
    }
  }

  async function archiveConversation(conversation: Conversation) {
    if (
      !window.confirm(
        `删除“${conversation.title}”？\n\n该会话将移入已归档，调研材料、证据和报告仍会保留。`,
      )
    ) {
      return;
    }
    setChangingConversation(conversation.id);
    setError("");
    try {
      await api.archiveConversation(conversation.id);
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
      if (conversation.id === conversationId) navigate("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除会话失败");
    } finally {
      setChangingConversation(null);
    }
  }

  async function restoreConversation(conversation: Conversation) {
    setChangingConversation(conversation.id);
    setError("");
    try {
      await api.restoreConversation(conversation.id);
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "恢复会话失败");
    } finally {
      setChangingConversation(null);
    }
  }

  function toggleArchived() {
    setConversations([]);
    setShowArchived((current) => !current);
    if (conversationId) navigate("/");
  }

  const updateSelectedConversation = useCallback((projection: ConversationProjection) => {
    const activeRun = [...projection.runs]
      .reverse()
      .find((run) => ["queued", "running", "stopping"].includes(run.status));
    setConversations((current) =>
      current.map((conversation) =>
        conversation.id === projection.conversation.id
          ? {
              ...projection.conversation,
              run_status: activeRun?.status ?? null,
              run_phase: activeRun?.phase ?? null,
            }
          : conversation,
      ),
    );
  }, []);

  return (
    <main className="conversation-workbench">
      <aside className="conversation-sidebar" aria-label="历史会话">
        {!showArchived && (
          <button className="new-conversation" type="button" onClick={createConversation}>
            <MessageSquarePlus size={17} />
            新建对话
          </button>
        )}
        <button className="archived-conversations" type="button" onClick={toggleArchived}>
          <ArchiveRestore size={16} />
          {showArchived ? "返回历史会话" : "查看已归档"}
        </button>
        {error && <p className="form-error sidebar-error">{error}</p>}
        <nav>
          {conversations.map((conversation) => (
            <div className="conversation-sidebar-item" key={conversation.id}>
              {showArchived ? (
                <div className="conversation-sidebar-item__label">
                  <strong>{conversation.title}</strong>
                  <small>已归档</small>
                </div>
              ) : (
                <button
                  className="conversation-sidebar-item__main"
                  type="button"
                  data-active={conversation.id === conversationId}
                  onClick={() => navigate(`/conversations/${conversation.id}`)}
                >
                  <strong>{conversation.title}</strong>
                  <small>
                    {conversation.run_status === "stopping"
                      ? "正在停止调研"
                      : conversation.run_status &&
                          ["queued", "running"].includes(conversation.run_status)
                        ? RUN_PHASE_LABELS[conversation.run_phase ?? "planning"]
                        : conversation.status === "intake"
                          ? "待明确调研目标"
                          : "调研会话"}
                  </small>
                </button>
              )}
              <button
                type="button"
                className="conversation-sidebar-item__action"
                disabled={changingConversation === conversation.id}
                aria-label={`${showArchived ? "恢复会话" : "删除会话"} ${conversation.title}`}
                onClick={() =>
                  void (showArchived
                    ? restoreConversation(conversation)
                    : archiveConversation(conversation))
                }
              >
                {showArchived ? <RotateCcw size={15} /> : <Trash2 size={15} />}
              </button>
            </div>
          ))}
          {conversations.length === 0 && showArchived && (
            <p className="conversation-sidebar-empty">暂无已归档会话</p>
          )}
        </nav>
      </aside>
      {conversationId ? (
        <ConversationPanel
          key={conversationId}
          conversationId={conversationId}
          onOpenContext={setContext}
          onProjectionChange={updateSelectedConversation}
        />
      ) : (
        <section className="workbench-empty">
          <MessageSquarePlus size={34} />
          <h1>从一个问题开始调研</h1>
          <p>可以先询问系统能力，也可以直接描述需要调查的主题、范围和产出。</p>
          <button className="primary-button" type="button" onClick={createConversation}>
            新建对话
          </button>
          {error && <p className="form-error">{error}</p>}
        </section>
      )}
      {context && (
        <ContextPanel selection={context} onSelect={setContext} onClose={() => setContext(null)} />
      )}
    </main>
  );
}
