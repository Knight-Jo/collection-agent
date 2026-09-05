import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { conversationKeys } from "./use-conversations";

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: conversationKeys.detail(id ?? ""),
    queryFn: () => api.conversation(id ?? ""),
    enabled: Boolean(id),
  });
}

export function useSendMessage(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => api.sendMessage(id, content),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.detail(id) }),
  });
}
