import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { factCheckKeys } from "./use-fact-checks";

export function useFactCheckStream(checkId: string | undefined) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!checkId) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({
        queryKey: factCheckKeys.detail(checkId),
      });
    }, 3000);
    return () => clearInterval(timer);
  }, [checkId, queryClient]);
}
