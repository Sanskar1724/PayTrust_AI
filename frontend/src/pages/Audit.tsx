import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, Empty, ErrorNote, PageHeader, Spinner } from "../components/ui";
import { api, query } from "../lib/api";
import { formatTime, humanize } from "../lib/format";
import type { AuditEvent, Page } from "../lib/types";

const TYPES = ["PAYMENT_EVALUATED", "PAYMENT_APPROVED", "PAYMENT_REJECTED", "APPROVAL_EXPIRED", "AI_INVESTIGATED", "ORDER_CREATED",
  "ORDER_FAILED", "CALLBACK_DELIVERED", "CALLBACK_FAILED", "POLICY_UPDATED", "AGENT_CREATED", "AGENT_UPDATED", "API_KEY_CREATED",
  "API_KEY_REVOKED", "OPERATOR_LOGIN", "OPERATOR_CREATED", "OPERATOR_UPDATED", "WEBHOOK_RECEIVED"];
const PAGE_SIZE = 50;

export function Audit() {
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const params = { event_type: type, limit: PAGE_SIZE, offset };
  const events = useQuery({ queryKey: ["audit", params], queryFn: () => api<Page<AuditEvent>>(`/v1/audit${query(params)}`), placeholderData: keepPreviousData });

  return (
    <>
      <PageHeader title="Audit log" description="Append-only record of every decision, review and configuration change, written in the same transaction as the change." />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-5 py-3">
          <select className="input w-auto" value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }}>
            <option value="">All events</option>
            {TYPES.map((t) => <option key={t} value={t}>{humanize(t.toLowerCase())}</option>)}
          </select>
        </div>
        {events.isLoading ? <Spinner /> : events.error ? <div className="p-5"><ErrorNote error={events.error} /></div> : !events.data?.items.length ? <Empty title="No events" /> : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="table-head"><tr><th className="px-5 py-2.5">When</th><th className="px-3 py-2.5">Event</th><th className="px-3 py-2.5">Actor</th><th className="px-3 py-2.5">Payment</th><th className="px-5 py-2.5">Details</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {events.data.items.map((e) => {
                    const { trace_id, ...data } = e.data;
                    return (
                      <tr key={e.id} className="align-top">
                        <td className="whitespace-nowrap px-5 py-2.5 text-xs text-slate-500">{formatTime(e.created_at)}</td>
                        <td className="px-3 py-2.5 font-medium text-slate-800">{humanize(e.event_type.toLowerCase())}</td>
                        <td className="px-3 py-2.5 text-xs text-slate-600">{e.actor}</td>
                        <td className="px-3 py-2.5">{e.request_id ? <Link className="font-mono text-xs text-brand-700 hover:underline" to={`/payments/${e.request_id}`}>{e.request_id}</Link> : "—"}</td>
                        <td className="px-5 py-2.5 font-mono text-[11px] text-slate-500" title={`trace ${String(trace_id ?? "")}`}>
                          {Object.entries(data).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ").slice(0, 220)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
              <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, events.data.total)} of {events.data.total}</span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={offset + PAGE_SIZE >= events.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
