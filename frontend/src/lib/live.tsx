import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { API_BASE, getToken } from "./api";
import type { ArenaRun, PaymentSummary } from "./types";

// One EventSource per tab. Incoming decisions refresh cached queries and feed the live ticker.
interface LiveState {
  connected: boolean;
  recent: PaymentSummary[];
  arena: Pick<ArenaRun, "id" | "status" | "stats" | "error"> | null;
}

const LiveContext = createContext<LiveState>({ connected: false, recent: [], arena: null });
const MAX_RECENT = 40;

export function LiveProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<LiveState>({ connected: false, recent: [], arena: null });
  const invalidateTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    if (!token) return;
    const source = new EventSource(`${API_BASE}/v1/stream?token=${encodeURIComponent(token)}`);

    // Batch cache refreshes: during an Arena run dozens of events arrive per second.
    const scheduleInvalidate = () => {
      if (invalidateTimer.current) return;
      invalidateTimer.current = window.setTimeout(() => {
        invalidateTimer.current = undefined;
        queryClient.invalidateQueries({ queryKey: ["payments"] });
        queryClient.invalidateQueries({ queryKey: ["stats"] });
        queryClient.invalidateQueries({ queryKey: ["payment"] });
      }, 800);
    };

    const onPayment = (e: MessageEvent) => {
      const p = JSON.parse(e.data) as PaymentSummary;
      setState((s) => {
        const without = s.recent.filter((r) => r.request_id !== p.request_id);
        return { ...s, recent: [p, ...without].slice(0, MAX_RECENT) };
      });
      scheduleInvalidate();
    };
    source.addEventListener("payment.created", onPayment);
    source.addEventListener("payment.updated", onPayment);
    source.addEventListener("arena.progress", (e) => {
      const run = JSON.parse((e as MessageEvent).data);
      setState((s) => ({ ...s, arena: run }));
      if (run.status !== "RUNNING") queryClient.invalidateQueries({ queryKey: ["arena"] });
    });
    source.onopen = () => setState((s) => ({ ...s, connected: true }));
    source.onerror = () => setState((s) => ({ ...s, connected: false })); // EventSource retries on its own

    return () => {
      source.close();
      window.clearTimeout(invalidateTimer.current);
      invalidateTimer.current = undefined;
    };
  }, [enabled, queryClient]);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);
