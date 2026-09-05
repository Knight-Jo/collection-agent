import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export const aiSearchToolKeys = {
  all: ["ai-search-tools"] as const,
};

export function useAiSearchTools() {
  return useQuery({
    queryKey: aiSearchToolKeys.all,
    queryFn: () => api.aiSearchTools(),
  });
}

export function useToggleAiSearchTool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.toggleAiSearchTool(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: aiSearchToolKeys.all }),
  });
}

export function useUpdateAiSearchToolApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, apiKey }: { id: string; apiKey: string }) =>
      api.updateAiSearchToolApiKey(id, apiKey),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: aiSearchToolKeys.all }),
  });
}
