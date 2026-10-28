import clsx from "clsx";
import { AlertTriangle, Bot, CheckCircle2, Sparkles, XCircle } from "lucide-react";
import { formatINR, formatPct, humanize } from "../lib/format";
import type { Payment } from "../lib/types";
import { Badge, Button, Card, DecisionBadge, RiskMeter, StatusBadge } from "./ui";

const SEVERITY: Record<string, string> = {
  critical: "bg-rose-600 text-white ring-rose-600",
  high: "bg-rose-50 text-rose-700 ring-rose-600/20",
  medium: "bg-amber-50 text-amber-800 ring-amber-600/25",
  low: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

export function DecisionHero({ p }: { p: Payment }) {
  const tone = p.decision === "ALLOW" ? "border-emerald-200 bg-emerald-50/60" : p.decision === "DENY" ? "border-rose-200 bg-rose-50/60" : "border-amber-200 bg-amber-50/60";
  const Icon = p.decision === "ALLOW" ? CheckCircle2 : p.decision === "DENY" ? XCircle : AlertTriangle;
  const iconTone = p.decision === "ALLOW" ? "text-emerald-600" : p.decision === "DENY" ? "text-rose-600" : "text-amber-600";
  return (
    <div className={clsx("rounded-xl border p-5", tone)}>
      <div className="flex flex-wrap items-start gap-4">
        <Icon className={clsx("mt-0.5 size-7 shrink-0", iconTone)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <DecisionBadge decision={p.decision} />
            <StatusBadge status={p.status} />
            {p.duplicate && <Badge>Idempotent replay</Badge>}
          </div>
          <div className="mt-2 text-lg font-semibold text-slate-900">
            {formatINR(p.amount)} to {p.merchant_name}
          </div>
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {p.reasons.map((r) => <li key={r}>• {r}</li>)}
          </ul>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Risk score</div>
          <div className="text-3xl font-semibold tabular-nums text-slate-900">{p.risk_score}</div>
          <div className="text-xs font-medium text-slate-600">{p.risk_level}</div>
          <div className="mt-1 text-[11px] text-slate-400">decided in {p.processing_ms.toFixed(1)} ms</div>
        </div>
      </div>
    </div>
  );
}

export function PolicyCard({ p }: { p: Payment }) {
  const pol = p.policy_result;
  const limit = pol.policy?.daily_limit;
  const after = pol.daily_spent + p.amount;
  return (
    <Card title="Policy check">
      {pol.violations.length ? (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {pol.violations.map((v) => <Badge key={v} className="bg-rose-50 text-rose-700 ring-rose-600/20">{humanize(v)}</Badge>)}
        </div>
      ) : (
        <div className="mb-3"><Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">No violations</Badge></div>
      )}
      <ul className="space-y-1.5 text-sm text-slate-700">
        {pol.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
      {pol.policy && limit != null && (
        <div className="mt-4 space-y-2 border-t border-slate-100 pt-4 text-xs text-slate-600">
          <div className="flex justify-between"><span>Spent today before this</span><span className="tabular-nums">{formatINR(pol.daily_spent)}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="flex h-full">
              <div className="bg-slate-400" style={{ width: `${Math.min(100, (pol.daily_spent / limit) * 100)}%` }} />
              <div className={after > limit ? "bg-rose-500" : "bg-brand-500"} style={{ width: `${Math.min(100 - Math.min(100, (pol.daily_spent / limit) * 100), (p.amount / limit) * 100)}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 pt-1">
            <div><div className="text-slate-400">Daily limit</div><div className="font-medium tabular-nums text-slate-800">{formatINR(limit)}</div></div>
            <div><div className="text-slate-400">Max per payment</div><div className="font-medium tabular-nums text-slate-800">{formatINR(pol.policy.max_transaction)}</div></div>
            <div><div className="text-slate-400">Approval above</div><div className="font-medium tabular-nums text-slate-800">{formatINR(pol.policy.approval_threshold)}</div></div>
          </div>
        </div>
      )}
    </Card>
  );
}

export function RiskCard({ p }: { p: Payment }) {
  const factors = p.risk_result.factors;
  return (
    <Card title="Risk factors" action={<RiskMeter score={p.risk_score} />}>
      {factors.length === 0 ? (
        <p className="text-sm text-slate-500">No risk signals fired.</p>
      ) : (
        <ul className="space-y-2.5">
          {factors.map((f, i) => (
            <li key={i} className="flex items-start gap-3">
              <Badge className={SEVERITY[f.severity]}>+{f.score}</Badge>
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-800">{humanize(f.name)}</div>
                <div className="text-xs text-slate-500">{f.details}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function SimulationCard({ p }: { p: Payment }) {
  const sim = p.simulation;
  const max = Math.max(...sim.counterfactuals.map((c) => c.expected_total_cost), 1);
  return (
    <Card title="What if we decided differently?" action={<Badge>Simulated</Badge>}>
      <div className="space-y-3">
        {sim.counterfactuals.map((c) => (
          <div key={c.action}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="flex items-center gap-2">
                <DecisionBadge decision={c.action} />
                {c.action === sim.recommended && <span className="font-medium text-brand-700">lowest safe cost</span>}
                {!c.allowed_by_policy && <span className="text-rose-600">blocked by policy</span>}
              </span>
              <span className="tabular-nums font-medium text-slate-800">{formatINR(c.expected_total_cost)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div className={clsx("h-full rounded-full", c.action === sim.recommended ? "bg-brand-500" : "bg-slate-300")} style={{ width: `${(c.expected_total_cost / max) * 100}%` }} />
            </div>
            <div className="mt-1 text-[11px] text-slate-500">
              fraud exposure {formatINR(c.fraud_exposure)} · false-positive cost {formatINR(c.false_positive_cost)} · ops {formatINR(c.operational_cost)}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-slate-500">{sim.reason} {sim.disclaimer}.</p>
    </Card>
  );
}

export function AiCard({ p, onInvestigate, busy, canRun }: { p: Payment; onInvestigate?: () => void; busy?: boolean; canRun?: boolean }) {
  return (
    <Card
      title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-brand-500" /> AI investigation</span>}
      action={canRun && onInvestigate && (
        <Button size="sm" variant="secondary" loading={busy} onClick={onInvestigate}>{p.ai ? "Re-run" : "Explain"}</Button>
      )}
    >
      {!p.ai ? (
        <p className="text-sm text-slate-500">
          {p.status === "PENDING_APPROVAL" ? "Generating an explanation for the reviewer…" : "Ask the AI to explain this decision in plain language."}
        </p>
      ) : (
        <div className="space-y-4 text-sm">
          <p className="leading-relaxed text-slate-800">{p.ai.explanation}</p>
          {p.ai.concerns.length > 0 && (
            <div>
              <div className="label">Concerns</div>
              <ul className="space-y-1 text-slate-700">{p.ai.concerns.map((c) => <li key={c}>• {c}</li>)}</ul>
            </div>
          )}
          {p.ai.review_questions.length > 0 && (
            <div>
              <div className="label">Ask before approving</div>
              <ul className="space-y-1 text-slate-700">{p.ai.review_questions.map((q) => <li key={q}>• {q}</li>)}</ul>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-[11px] text-slate-500">
            <Bot className="size-3.5" /> {p.ai.provider} · {p.ai.model} · confidence {formatPct(p.ai.confidence)}
            <span className="ml-auto">Advisory only — never changes the decision</span>
          </div>
        </div>
      )}
    </Card>
  );
}
