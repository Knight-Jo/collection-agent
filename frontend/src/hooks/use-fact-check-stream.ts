import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { subscribeFactCheck } from "@/mocks/sse";
import { factCheckKeys } from "./use-fact-checks";

export function useFactCheckStream(checkId: string | undefined) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!checkId) return;
    return subscribeFactCheck(checkId, () => {
      void queryClient.invalidateQueries({ queryKey: factCheckKeys.detail(checkId) });
      void queryClient.invalidateQueries({ queryKey: factCheckKeys.all });
    });
  }, [checkId, queryClient]);
}
