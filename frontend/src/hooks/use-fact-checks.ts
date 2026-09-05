import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export const factCheckKeys = {
  all: ["fact-checks"] as const,
  list: () => ["fact-checks", "list"] as const,
  detail: (id: string) => ["fact-checks", "detail", id] as const,
};

export function useFactChecks() {
  return useQuery({
    queryKey: factCheckKeys.list(),
    queryFn: () => api.factChecks(),
  });
}

export function useFactCheck(id: string | undefined) {
  return useQuery({
    queryKey: factCheckKeys.detail(id ?? ""),
    queryFn: () => api.factCheck(id ?? ""),
    enabled: Boolean(id),
  });
}

export function useCreateFactCheck() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (claim: string) => api.createFactCheck(claim),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: factCheckKeys.all }),
  });
}
