import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PaymentTable } from "../components/PaymentTable";
import { Card, Empty, PageHeader, Spinner, Stat } from "../components/ui";
import { api } from "../lib/api";
import { formatINR, formatNumber, humanize } from "../lib/format";
import { useLive } from "../lib/live";
import type { Page, PaymentSummary, Stats } from "../lib/types";

const COLORS = { ALLOW: "#10b981", ASK_USER: "#f59e0b", DENY: "#e11d48" };

export function Overview() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/v1/stats") });
  const latest = useQuery({ queryKey: ["payments", "latest"], queryFn: () => api<Page<PaymentSummary>>("/v1/payments?limit=8") });
  const { recent } = useLive();

  if (stats.isLoading) return <Spinner />;
  const s = stats.data;
  if (!s) return null;
  const rows = latest.data?.items ?? recent.slice(0, 8);
  const blockRate = s.total ? (s.decisions.DENY / s.total) * 100 : 0;

  return (
    <>
      <PageHeader title="Overview" description="Every decision in the last 24 hours. Updates live as agents submit payments." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Payments evaluated" value={formatNumber(s.total)} hint={`${formatNumber(s.decisions.ALLOW)} allowed · ${formatNumber(s.decisions.ASK_USER)} asked · ${formatNumber(s.decisions.DENY)} denied`} />
        <Stat label="Waiting for approval" value={formatNumber(s.pending_approvals)} tone={s.pending_approvals ? "warn" : undefined}
          hint={<Link to="/approvals" className="text-brand-600 hover:underline">Open approvals inbox →</Link>} />
        <Stat label="Blocked amount" value={formatINR(s.amount_blocked)} tone="bad" hint={`${blockRate.toFixed(1)}% of payments denied`} />
        <Stat label="Decision latency" value={`${s.latency_ms.p95.toFixed(1)} ms`} hint={`p95 · p50 ${s.latency_ms.p50.toFixed(1)} ms`} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Decisions per hour" className="lg:col-span-2">
          {s.total === 0 ? (
            <Empty title="No traffic yet">Send a payment from the Playground or start an Agent Arena run.</Empty>
          ) : (
            <div className="h-64">
              <ResponsiveContainer>
                <BarChart data={s.series} margin={{ left: -20, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="hour" tickFormatter={(h: string) => h.slice(11, 16)} tick={{ fontSize: 11, fill: "#64748b" }} interval={3} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} />
                  <Tooltip cursor={{ fill: "#f1f5f9" }} labelFormatter={(h) => new Date(String(h)).toLocaleString("en-IN", { hour: "numeric", day: "numeric", month: "short" })} />
                  <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" />
                  {(["ALLOW", "ASK_USER", "DENY"] as const).map((k, i) => (
                    <Bar key={k} dataKey={k} stackId="1" fill={COLORS[k]} maxBarSize={28} radius={i === 2 ? [3, 3, 0, 0] : 0} name={k === "ASK_USER" ? "Ask user" : humanize(k.toLowerCase())} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Why payments are stopped">
          {s.top_violations.length === 0 && s.top_factors.length === 0 ? (
            <Empty title="Nothing stopped yet" />
          ) : (
            <div className="space-y-5">
              <Breakdown title="Policy violations" rows={s.top_violations} color="bg-rose-500" />
              <Breakdown title="Risk signals" rows={s.top_factors} color="bg-amber-400" />
            </div>
          )}
        </Card>
      </div>

      <Card title="Latest payments" className="mt-6" padded={false} action={<Link to="/payments" className="text-xs font-medium text-brand-600 hover:underline">View all</Link>}>
        <PaymentTable rows={rows} compact />
      </Card>
    </>
  );
}

function Breakdown({ title, rows, color }: { title: string; rows: [string, number][]; color: string }) {
  const max = Math.max(...rows.map((r) => r[1]), 1);
  return (
    <div>
      <div className="label">{title}</div>
      <ul className="space-y-2">
        {rows.map(([name, count]) => (
          <li key={name}>
            <div className="flex justify-between text-xs text-slate-700"><span>{humanize(name)}</span><span className="tabular-nums">{count}</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${color}`} style={{ width: `${(count / max) * 100}%` }} /></div>
          </li>
        ))}
      </ul>
    </div>
  );
}
