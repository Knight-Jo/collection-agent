import type { AgentEvent } from "@/api/types";

type Handler = (event: AgentEvent) => void;

const EVENT_TYPES = [
  "run.status",
  "run.phase",
  "timeline",
  "material",
  "answer.started",
  "answer.delta",
  "answer.completed",
  "refetch",
] as const;

/**
 * Subscribe to a conversation's server-sent events. Returns an unsubscribe
 * function, mirroring the mock `subscribe` API so the hooks stay unchanged.
 */
export function subscribeAgent(
  conversationId: string,
  handler: Handler,
): () => void {
  const source = new EventSource(
    `/api/conversations/${conversationId}/events`,
  );
  for (const eventType of EVENT_TYPES) {
    source.addEventListener(eventType, (event) => {
      const data = JSON.parse((event as MessageEvent).data) as AgentEvent;
      handler(data);
    });
  }
  return () => source.close();
}
