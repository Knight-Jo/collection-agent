import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export const mediaKeys = {
  all: ["media"] as const,
  list: () => ["media", "list"] as const,
  detail: (id: string) => ["media", "detail", id] as const,
};

export function useMediaJobs() {
  return useQuery({
    queryKey: mediaKeys.list(),
    queryFn: () => api.mediaJobs(),
  });
}

export function useMediaJob(id: string | undefined) {
  return useQuery({
    queryKey: mediaKeys.detail(id ?? ""),
    queryFn: () => api.mediaJob(id ?? ""),
    enabled: Boolean(id),
  });
}

export function useCreateMediaJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { filename: string; kind: "audio" | "video"; size: number }) =>
      api.createMediaJob(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: mediaKeys.all }),
  });
}
