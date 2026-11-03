import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, API_BASE, getToken } from "./api";
import type { ArenaRun, PaymentSummary } from "./types";

// One EventSource per tab. Incoming decisions refresh cached queries and feed the live ticker.
// The stream is opened with a short-lived ticket (never the session token, which would end up
// in URL logs). A ticket expires in 60 s, so the browser's own reconnect would fail: on any
// error we close the source and reconnect with a fresh ticket, backing off up to 30 s.
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
    if (!enabled || !getToken()) return;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;
    let backoff = 1000;
    let stopped = false;

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
    const onArena = (e: Event) => {
      const run = JSON.parse((e as MessageEvent).data);
      setState((s) => ({ ...s, arena: run }));
      if (run.status !== "RUNNING") queryClient.invalidateQueries({ queryKey: ["arena"] });
    };

    const reconnectLater = () => {
      if (stopped) return;
      window.clearTimeout(retryTimer);
      retryTimer = window.setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 30_000);
    };

    async function connect() {
      if (stopped) return;
      let ticket: string;
      try {
        ticket = (await api<{ ticket: string }>("/v1/stream/ticket", { method: "POST" })).ticket;
      } catch {
        return reconnectLater(); // a 401 here also signs the user out via the api() handler
      }
      if (stopped) return;
      const es = new EventSource(`${API_BASE}/v1/stream?ticket=${encodeURIComponent(ticket)}`);
      source = es;
      es.addEventListener("payment.created", onPayment);
      es.addEventListener("payment.updated", onPayment);
      es.addEventListener("arena.progress", onArena);
      es.onopen = () => {
        backoff = 1000;
        setState((s) => ({ ...s, connected: true }));
      };
      es.onerror = () => {
        es.close();
        if (source === es) source = null;
        setState((s) => ({ ...s, connected: false }));
        reconnectLater();
      };
    }
    connect();

    return () => {
      stopped = true;
      source?.close();
      window.clearTimeout(retryTimer);
      window.clearTimeout(invalidateTimer.current);
      invalidateTimer.current = undefined;
    };
  }, [enabled, queryClient]);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);
