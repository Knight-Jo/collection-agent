import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { subscribeMedia } from "@/mocks/sse";
import { mediaKeys } from "./use-media";

export function useMediaStream(jobId: string | undefined) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId) return;
    return subscribeMedia(jobId, () => {
      void queryClient.invalidateQueries({ queryKey: mediaKeys.detail(jobId) });
      void queryClient.invalidateQueries({ queryKey: mediaKeys.all });
    });
  }, [jobId, queryClient]);
}
