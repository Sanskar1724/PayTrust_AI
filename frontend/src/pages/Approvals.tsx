import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, DecisionBadge, Empty, ErrorNote, PageHeader, RiskMeter, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { formatINR, humanize, timeAgo } from "../lib/format";
import type { Page, Payment, PaymentSummary } from "../lib/types";
import { ReviewBar } from "./Payments";

export function Approvals() {
  const queryClient = useQueryClient();
  const pending = useQuery({
    queryKey: ["payments", "pending"],
    queryFn: () => api<Page<PaymentSummary>>("/v1/payments?status=PENDING_APPROVAL&limit=100"),
    refetchInterval: 15_000,
  });
  const done = (p: Payment) => {
    queryClient.invalidateQueries({ queryKey: ["payments"] });
    queryClient.invalidateQueries({ queryKey: ["stats"] });
    queryClient.setQueryData(["payment", p.request_id], p);
  };

  return (
    <>
      <PageHeader title="Approvals" description="Payments the engines sent to a human. Each one reserves its amount against the user's daily limit until it is approved, rejected or expires." />
      {pending.isLoading ? <Spinner /> : pending.error ? <ErrorNote error={pending.error} /> : !pending.data?.items.length ? (
        <Card><Empty title="Inbox zero">No payments are waiting for approval.</Empty></Card>
      ) : (
        <div className="space-y-4">
          {pending.data.items.map((p) => (
            <Card key={p.request_id}>
              <div className="flex flex-wrap items-center gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <DecisionBadge decision={p.decision} />
                    <Link to={`/payments/${p.request_id}`} className="font-mono text-xs text-brand-700 hover:underline">{p.request_id}</Link>
                    <span className="text-xs text-slate-400">{timeAgo(p.created_at)}</span>
                  </div>
                  <div className="mt-1.5 text-base font-semibold text-slate-900">{formatINR(p.amount)} · {p.merchant_name}</div>
                  <div className="text-xs text-slate-500">{humanize(p.category)} · user {p.user_id} · agent {p.agent_id}</div>
                </div>
                <RiskMeter score={p.risk_score} />
                <Link to={`/payments/${p.request_id}`} className="text-sm font-medium text-brand-600 hover:underline">Evidence →</Link>
              </div>
              <ReviewBar p={p} onDone={done} />
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
