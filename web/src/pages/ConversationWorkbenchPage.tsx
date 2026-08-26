import { MessageSquarePlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ContextPanel } from "../components/ContextPanel";
import { type ContextSelection, ConversationPanel } from "../components/ConversationPanel";
import type { Conversation } from "../types";

export function ConversationWorkbenchPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [context, setContext] = useState<ContextSelection | null>(null);

  const refresh = useCallback(async () => {
    try {
      setConversations(await api.conversations());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载历史会话失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createConversation() {
    try {
      const created = await api.createConversation();
      await refresh();
      navigate(`/conversations/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建对话失败");
    }
  }

  return (
    <main className="conversation-workbench">
      <aside className="conversation-sidebar" aria-label="历史会话">
        <button className="new-conversation" type="button" onClick={createConversation}>
          <MessageSquarePlus size={17} />
          新建对话
        </button>
        <nav>
          {conversations.map((conversation) => (
            <button
              type="button"
              key={conversation.id}
              data-active={conversation.id === conversationId}
              onClick={() => navigate(`/conversations/${conversation.id}`)}
            >
              <strong>{conversation.title}</strong>
              <small>{conversation.status === "intake" ? "待明确调研目标" : "调研会话"}</small>
            </button>
          ))}
        </nav>
      </aside>
      {conversationId ? (
        <ConversationPanel conversationId={conversationId} onOpenContext={setContext} />
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
