import type {
  Artifact,
  Conversation,
  ConversationAction,
  ConversationMessage,
  ConversationProjection,
  ReportVersion,
  ReportVersionDetail,
  ResearchRun,
  Run,
  RunInput,
  SearchPlanVersion,
  SystemStatus,
  TaskDetail,
  TaskSummary,
  TimelineEntry,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error?.message ?? `请求失败 (${response.status})`);
  }
  return body as T;
}

export const api = {
  system: () => request<SystemStatus>("/api/system"),
  tasks: () => request<TaskSummary[]>("/api/tasks"),
  task: (id: string) => request<TaskDetail>(`/api/tasks/${id}`),
  artifact: (id: string, kind: Artifact["kind"]) =>
    request<Artifact>(`/api/tasks/${id}/artifacts/${kind}`),
  createRun: (input: RunInput) =>
    request<Run>("/api/runs", { method: "POST", body: JSON.stringify(input) }),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  cancelRun: (id: string) => request<Run>(`/api/runs/${id}/cancel`, { method: "POST" }),
  conversation: (taskId: string) =>
    request<ConversationProjection>(`/api/tasks/${taskId}/conversation`),
  sendMessage: (taskId: string, content: string, clientMessageId: string) =>
    request<ConversationMessage>(`/api/tasks/${taskId}/conversation/messages`, {
      method: "POST",
      body: JSON.stringify({ content, client_message_id: clientMessageId }),
    }),
  cancelMessage: (messageId: string) =>
    request<ConversationMessage>(`/api/messages/${messageId}/cancel`, { method: "POST" }),
  retryMessage: (messageId: string) =>
    request<ConversationMessage>(`/api/messages/${messageId}/retry`, { method: "POST" }),
  confirmAction: (actionId: string, clientMessageId: string) =>
    request<ConversationAction>(`/api/action-requests/${actionId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ client_message_id: clientMessageId }),
    }),
  rejectAction: (actionId: string) =>
    request<ConversationAction>(`/api/action-requests/${actionId}/reject`, { method: "POST" }),
  cancelAction: (actionId: string) =>
    request<ConversationAction>(`/api/action-requests/${actionId}/cancel`, { method: "POST" }),
  cancelResearchRun: (runId: string) =>
    request<ResearchRun>(`/api/research-runs/${runId}/cancel`, { method: "POST" }),
  conversations: (archived = false) =>
    request<Conversation[]>(`/api/conversations${archived ? "?archived=true" : ""}`),
  createConversation: () =>
    request<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  archiveConversation: (conversationId: string) =>
    request<Conversation>(`/api/conversations/${conversationId}/archive`, { method: "POST" }),
  restoreConversation: (conversationId: string) =>
    request<Conversation>(`/api/conversations/${conversationId}/restore`, { method: "POST" }),
  conversationById: (conversationId: string) =>
    request<ConversationProjection>(`/api/conversations/${conversationId}`),
  sendConversationMessage: (conversationId: string, content: string, clientMessageId: string) =>
    request<ConversationMessage>(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, client_message_id: clientMessageId }),
    }),
  timeline: (conversationId: string, afterSequence = 0) =>
    request<TimelineEntry[]>(
      `/api/conversations/${conversationId}/timeline?after_sequence=${afterSequence}`,
    ),
  stopResearchRun: (runId: string) =>
    request<ResearchRun>(`/api/research-runs/${runId}/stop`, { method: "POST" }),
  researchRun: (runId: string) => request<ResearchRun>(`/api/research-runs/${runId}`),
  searchPlanVersion: (planId: string) =>
    request<SearchPlanVersion>(`/api/search-plan-versions/${planId}`),
  activeSearchPlan: (runId: string) =>
    request<SearchPlanVersion>(`/api/research-runs/${runId}/search-plan`),
  reportVersion: (reportId: string) =>
    request<ReportVersionDetail>(`/api/report-versions/${reportId}`),
  createReportVersion: (taskId: string) =>
    request<ReportVersion>(`/api/tasks/${taskId}/report-versions`, { method: "POST" }),
  publishReportVersion: (reportId: string, expectedStateVersion?: number) =>
    request<ReportVersion>(`/api/report-versions/${reportId}/publish`, {
      method: "POST",
      body: JSON.stringify(
        expectedStateVersion === undefined
          ? {}
          : { publish_stale: true, expected_current_state_version: expectedStateVersion },
      ),
    }),
};
