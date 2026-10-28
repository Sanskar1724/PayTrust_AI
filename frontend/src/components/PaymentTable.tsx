import { useNavigate } from "react-router-dom";
import { formatINR, humanize, timeAgo } from "../lib/format";
import type { PaymentSummary } from "../lib/types";
import { DecisionBadge, Empty, RiskMeter, StatusBadge } from "./ui";

export function PaymentTable({ rows, empty = "No payments yet", compact }: { rows: PaymentSummary[]; empty?: string; compact?: boolean }) {
  const navigate = useNavigate();
  if (!rows.length) return <Empty title={empty}>Payments appear here the moment an agent submits them.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="table-head">
          <tr>
            <th className="px-5 py-2.5">Request</th>
            <th className="px-3 py-2.5">Merchant</th>
            <th className="px-3 py-2.5 text-right">Amount</th>
            <th className="px-3 py-2.5">Decision</th>
            {!compact && <th className="px-3 py-2.5">Status</th>}
            <th className="px-3 py-2.5">Risk</th>
            <th className="px-5 py-2.5 text-right">When</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((p) => (
            <tr key={p.request_id} onClick={() => navigate(`/payments/${p.request_id}`)} className="cursor-pointer hover:bg-slate-50">
              <td className="px-5 py-2.5">
                <div className="font-mono text-xs text-slate-900">{p.request_id}</div>
                <div className="text-[11px] text-slate-400">user {p.user_id} · agent {p.agent_id}{p.source !== "api" && ` · ${p.source}`}</div>
              </td>
              <td className="px-3 py-2.5">
                <div className="text-slate-800">{p.merchant_name}</div>
                <div className="text-[11px] text-slate-400">{humanize(p.category)}</div>
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums font-medium text-slate-900">{formatINR(p.amount)}</td>
              <td className="px-3 py-2.5"><DecisionBadge decision={p.decision} /></td>
              {!compact && <td className="px-3 py-2.5"><StatusBadge status={p.status} /></td>}
              <td className="px-3 py-2.5"><RiskMeter score={p.risk_score} compact /></td>
              <td className="whitespace-nowrap px-5 py-2.5 text-right text-xs text-slate-500">{timeAgo(p.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
