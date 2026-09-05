import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export const systemKeys = {
  status: ["system"] as const,
};

export function useSystem() {
  return useQuery({
    queryKey: systemKeys.status,
    queryFn: () => api.system(),
  });
}

export const libraryKeys = {
  all: ["library"] as const,
};

export function useLibrary() {
  return useQuery({
    queryKey: libraryKeys.all,
    queryFn: () => api.library(),
  });
}
