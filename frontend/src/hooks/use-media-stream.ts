import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { mediaKeys } from "./use-media";

export function useMediaStream(jobId: string | undefined) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: mediaKeys.detail(jobId) });
    }, 3000);
    return () => clearInterval(timer);
  }, [jobId, queryClient]);
}
