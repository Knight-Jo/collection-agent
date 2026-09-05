import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { subscribe } from "@/mocks/sse";
import { conversationKeys } from "./use-conversations";

const MUTATING_EVENTS = new Set(["run.status", "run.phase", "timeline", "material", "refetch"]);

export function useAgentStream(conversationId: string | undefined) {
  const queryClient = useQueryClient();
  const [streaming, setStreaming] = useState("");

  useEffect(() => {
    if (!conversationId) return;
    setStreaming("");
    return subscribe(conversationId, (event) => {
      if (MUTATING_EVENTS.has(event.type)) {
        void queryClient.invalidateQueries({
          queryKey: conversationKeys.detail(conversationId),
        });
        void queryClient.invalidateQueries({ queryKey: conversationKeys.all });
        return;
      }
      if (event.type === "answer.started") {
        setStreaming("");
        return;
      }
      if (event.type === "answer.delta") {
        setStreaming((current) => current + event.delta);
        return;
      }
      if (event.type === "answer.completed") {
        setStreaming("");
      }
    });
  }, [conversationId, queryClient]);

  return { streaming, active: streaming !== "" };
}
