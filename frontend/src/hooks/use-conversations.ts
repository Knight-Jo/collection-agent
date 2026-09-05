import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ResearchBrief } from "@/api/types";

export const conversationKeys = {
  all: ["conversations"] as const,
  list: (archived: boolean) => ["conversations", "list", archived] as const,
  detail: (id: string) => ["conversations", "detail", id] as const,
};

export function useConversations(archived = false) {
  return useQuery({
    queryKey: conversationKeys.list(archived),
    queryFn: () => api.conversations(archived),
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.createConversation(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

export function useArchiveConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.archiveConversation(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

export function useRestoreConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.restoreConversation(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

export function useGenerateBrief() {
  return useMutation({
    mutationFn: (prompt: string) => api.generateBrief(prompt),
  });
}

export function useStartResearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ topic, brief }: { topic: string; brief: ResearchBrief }) =>
      api.startResearch(topic, brief),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}
