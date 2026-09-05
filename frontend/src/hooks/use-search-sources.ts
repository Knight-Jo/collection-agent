import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export const searchSourceKeys = {
  all: ["search-sources"] as const,
};

export function useSearchSources() {
  return useQuery({
    queryKey: searchSourceKeys.all,
    queryFn: () => api.searchSources(),
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: searchSourceKeys.all });
}

export function useToggleSearchSource() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.toggleSearchSource(id),
    onSuccess: invalidate,
  });
}

export function useUpdateSearchSource() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, cookies }: { id: string; cookies: string }) =>
      api.updateSearchSource(id, { cookies }),
    onSuccess: invalidate,
  });
}

export function useAddSearchSource() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: { name: string; url: string }) => api.addSearchSource(input),
    onSuccess: invalidate,
  });
}
