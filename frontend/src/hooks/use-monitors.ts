import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export const monitorKeys = {
  all: ["monitors"] as const,
  list: () => ["monitors", "list"] as const,
  detail: (id: string) => ["monitors", "detail", id] as const,
};

export function useMonitors() {
  return useQuery({
    queryKey: monitorKeys.list(),
    queryFn: () => api.monitors(),
  });
}

export function useMonitor(id: string | undefined) {
  return useQuery({
    queryKey: monitorKeys.detail(id ?? ""),
    queryFn: () => api.monitor(id ?? ""),
    enabled: Boolean(id),
  });
}

export function useCreateMonitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      name: string;
      subject: string;
      strategy: string;
      frequency: string;
      questions: string[];
      websites: string[];
    }) => api.createMonitor(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: monitorKeys.all }),
  });
}

export function useToggleMonitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.toggleMonitor(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: monitorKeys.all }),
  });
}

export function useRunMonitorNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.runMonitorNow(id),
    onSuccess: (_data, id) => queryClient.invalidateQueries({ queryKey: monitorKeys.detail(id) }),
  });
}
