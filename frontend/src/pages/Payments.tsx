import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, X } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AiCard, DecisionHero, PolicyCard, RiskCard, SimulationCard } from "../components/Evidence";
import { PaymentTable } from "../components/PaymentTable";
import { Button, Card, Empty, ErrorNote, PageHeader, Spinner, Tabs } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatINR, formatTime, humanize, timeUntil } from "../lib/format";
import type { AuditEvent, Page, Payment, PaymentSummary } from "../lib/types";

const PAGE_SIZE = 25;

export function Payments() {
  const [decision, setDecision] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [arena, setArena] = useState(false);
  const params = { decision, status, q: q.trim(), include_arena: arena, limit: PAGE_SIZE, offset };
  const list = useQuery({
    queryKey: ["payments", params],
    queryFn: () => api<Page<PaymentSummary>>(`/v1/payments${query(params)}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader title="Payments" description="Every payment request agents have submitted, with the decision and its evidence." />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-5 py-3">
          <Tabs value={decision} onChange={(v) => { setDecision(v); setOffset(0); }} options={[
            { value: "", label: "All" }, { value: "ALLOW", label: "Allowed" }, { value: "ASK_USER", label: "Ask user" }, { value: "DENY", label: "Denied" },
          ]} />
          <select className="input w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
            <option value="">Any status</option>
            {["ALLOWED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXPIRED", "DENIED"].map((s) => <option key={s} value={s}>{humanize(s.toLowerCase())}</option>)}
          </select>
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" className="size-4 accent-brand-600" checked={arena} onChange={(e) => { setArena(e.target.checked); setOffset(0); }} />
            Include Arena simulations
          </label>
          <input className="input w-full sm:ml-auto sm:w-64" placeholder="Search request id or merchant" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        </div>
        {list.isLoading ? <Spinner /> : list.error ? <div className="p-5"><ErrorNote error={list.error} /></div> : (
          <>
            <PaymentTable rows={list.data?.items ?? []} empty="No payments match these filters" />
            <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
              <span>{list.data?.total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, list.data.total)} of ${list.data.total}` : "0 results"}</span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={!list.data || offset + PAGE_SIZE >= list.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}

export function PaymentDetail() {
  const { requestId = "" } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const payment = useQuery({ queryKey: ["payment", requestId], queryFn: () => api<Payment>(`/v1/payments/${requestId}`) });
  const audit = useQuery({ queryKey: ["audit", requestId], queryFn: () => api<Page<AuditEvent>>(`/v1/audit${query({ request_id: requestId })}`) });
  const refresh = (p: Payment) => {
    queryClient.setQueryData(["payment", requestId], p);
    queryClient.invalidateQueries({ queryKey: ["audit", requestId] });
    queryClient.invalidateQueries({ queryKey: ["payments"] });
    queryClient.invalidateQueries({ queryKey: ["stats"] });
  };
  const investigate = useMutation({ mutationFn: () => api<Payment>(`/v1/payments/${requestId}/investigate`, { method: "POST" }), onSuccess: refresh });

  if (payment.isLoading) return <Spinner />;
  if (payment.error) return <ErrorNote error={payment.error} />;
  const p = payment.data!;

  return (
    <>
      <Link to="/payments" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="size-4" /> Payments
      </Link>
      <PageHeader title={p.request_id} description={`${formatTime(p.created_at)} · user ${p.user_id} · agent ${p.agent_id} · via ${p.source}`} />
      <DecisionHero p={p} />
      {p.status === "PENDING_APPROVAL" && <ReviewBar p={p} onDone={refresh} />}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <PolicyCard p={p} />
        <RiskCard p={p} />
        <AiCard p={p} canRun={can("reviewer")} busy={investigate.isPending} onInvestigate={() => investigate.mutate()} />
        <SimulationCard p={p} />
        <Card title="Request">
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-slate-500">Amount</dt><dd className="font-medium">{formatINR(p.amount)}</dd>
            <dt className="text-slate-500">Merchant</dt><dd>{p.merchant_name} (#{p.merchant_id})</dd>
            <dt className="text-slate-500">Category</dt><dd>{humanize(p.category)}</dd>
            <dt className="text-slate-500">Description</dt><dd>{p.description || "—"}</dd>
            <dt className="text-slate-500">Agent's reason</dt><dd>{p.agent_reason || "—"}</dd>
            {p.order && <><dt className="text-slate-500">Order</dt><dd className="font-mono text-xs">{p.order.id ?? p.order.error} {p.order.mode && `(${p.order.mode})`}</dd></>}
            {p.reviewed_by && <><dt className="text-slate-500">Reviewed</dt><dd>{p.reviewed_by} · {formatTime(p.reviewed_at)}{p.review_note && ` — “${p.review_note}”`}</dd></>}
          </dl>
        </Card>
        <Card title="Audit trail" padded={false}>
          {!audit.data?.items.length ? <Empty title="No events" /> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {audit.data.items.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <div><div className="font-medium text-slate-800">{humanize(e.event_type.toLowerCase())}</div><div className="text-xs text-slate-500">{e.actor}</div></div>
                  <div className="text-xs text-slate-500">{formatTime(e.created_at)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

export function ReviewBar({ p, onDone }: { p: Payment | PaymentSummary; onDone: (p: Payment) => void }) {
  const { can } = useAuth();
  const [note, setNote] = useState("");
  const review = useMutation({
    mutationFn: (approve: boolean) => api<Payment>(`/v1/payments/${p.request_id}/${approve ? "approve" : "reject"}`, { method: "POST", body: { note: note || null } }),
    onSuccess: onDone,
  });
  if (!can("reviewer")) return <p className="mt-4 text-sm text-slate-500">Waiting for a reviewer · {timeUntil(p.expires_at)}</p>;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-white p-4">
      <div className="text-sm text-slate-700"><span className="font-medium">Needs a decision</span> · <span className="text-amber-700">{timeUntil(p.expires_at)}</span></div>
      <input className="input min-w-48 flex-1" placeholder="Note for the audit log (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      <Button variant="success" icon={<Check className="size-4" />} loading={review.isPending && review.variables} onClick={() => review.mutate(true)}>Approve</Button>
      <Button variant="danger" icon={<X className="size-4" />} loading={review.isPending && !review.variables} onClick={() => review.mutate(false)}>Reject</Button>
      {review.error && <div className="w-full"><ErrorNote error={review.error} /></div>}
    </div>
  );
}
