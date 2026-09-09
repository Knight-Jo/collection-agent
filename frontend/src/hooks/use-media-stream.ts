import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { mediaKeys } from "./use-media";

/**
 * Poll a media job's detail while it is still processing.
 *
 * `enabled` must go false once the job reaches a terminal state, otherwise a
 * viewer parked on a finished transcript polls the backend forever (observed:
 * 489 requests for one completed job in an afternoon).
 */
export function useMediaStream(jobId: string | undefined, enabled: boolean = true) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId || !enabled) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({
        queryKey: mediaKeys.detail(jobId),
      });
    }, 3000);
    return () => clearInterval(timer);
  }, [jobId, enabled, queryClient]);
}
