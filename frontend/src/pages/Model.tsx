import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ErrorNote, PageHeader, Spinner, Stat } from "../components/ui";
import { api } from "../lib/api";
import { formatNumber, formatPct } from "../lib/format";
import type { ThresholdPoint } from "../lib/types";

interface Curves { points: ThresholdPoint[]; recommended: { max_f1: number; min_cost: number }; n: number; disclaimer: string }
interface Report { test: Record<string, number> | null; n_train: number; n_test: number; disclaimer: string }

const usd = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;

export function Model() {
  const curves = useQuery({ queryKey: ["ml", "curves"], queryFn: () => api<Curves>("/v1/ml/curves"), staleTime: Infinity });
  const report = useQuery({ queryKey: ["ml", "report"], queryFn: () => api<Report>("/v1/ml/report"), staleTime: Infinity });
  const [threshold, setThreshold] = useState(0.5);

  const point = useMemo(() => {
    const pts = curves.data?.points ?? [];
    return pts.reduce<ThresholdPoint | undefined>((best, p) => (!best || Math.abs(p.threshold - threshold) < Math.abs(best.threshold - threshold) ? p : best), undefined);
  }, [curves.data, threshold]);

  if (curves.isLoading) return <Spinner />;
  if (curves.error) return <ErrorNote error={curves.error} />;
  const c = curves.data!;
  const metrics = report.data?.test ?? {};

  return (
    <>
      <PageHeader
        title="ML model"
        description={`An advisory fraud model trained on the IEEE-CIS dataset (590k real card transactions), evaluated on ${formatNumber(c.n)} held-out test transactions. Pick where to draw the line and see what it costs. It does not change PayTrust decisions.`}
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="PR-AUC (held-out)" value={metrics.pr_auc != null ? metrics.pr_auc.toFixed(3) : "—"} hint="Honest headline at a 3.5% fraud rate" />
        <Stat label="ROC-AUC" value={metrics.roc_auc != null ? metrics.roc_auc.toFixed(3) : "—"} />
        <Stat label="Best F1 threshold" value={c.recommended.max_f1.toFixed(2)} />
        <Stat label="Lowest-cost threshold" value={c.recommended.min_cost.toFixed(2)} hint="Under the simulated cost model" />
      </div>

      <Card title="Choose an operating point" className="mt-6">
        <div className="flex flex-wrap items-center gap-4">
          <input type="range" min={0} max={1} step={0.01} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} className="flex-1 accent-brand-600" aria-label="Threshold" />
          <span className="w-28 text-right font-mono text-sm">flag if p ≥ {threshold.toFixed(2)}</span>
        </div>
        {point && (
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Precision" value={formatPct(point.precision, 1)} hint="Flagged payments that were fraud" />
            <Stat label="Recall" value={formatPct(point.recall, 1)} hint="Fraud that got flagged" />
            <Stat label="False-positive rate" value={formatPct(point.false_positive_rate, 1)} hint={`${formatNumber(point.fp)} honest customers flagged`} />
            <Stat label="Simulated total cost" value={usd(point.expected_total_cost)} hint={`fraud missed ${usd(point.fraud_exposure)} · friction ${usd(point.false_positive_cost)}`} />
          </div>
        )}
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="Precision, recall and F1">
          <div className="h-72">
            <ResponsiveContainer>
              <LineChart data={c.points} margin={{ left: -16, right: 8, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="threshold" type="number" domain={[0, 1]} tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => formatPct(Number(v), 1)} labelFormatter={(t) => `threshold ${Number(t).toFixed(2)}`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine x={threshold} stroke="#3b55e6" strokeDasharray="4 4" />
                <Line dataKey="precision" stroke="#3b55e6" dot={false} strokeWidth={2} />
                <Line dataKey="recall" stroke="#10b981" dot={false} strokeWidth={2} />
                <Line dataKey="f1" stroke="#f59e0b" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Simulated cost by threshold">
          <div className="h-72">
            <ResponsiveContainer>
              <LineChart data={c.points} margin={{ left: 8, right: 8, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="threshold" type="number" domain={[0, 1]} tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Math.round(Number(v) / 1000)}k`} />
                <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={(t) => `threshold ${Number(t).toFixed(2)}`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine x={threshold} stroke="#3b55e6" strokeDasharray="4 4" />
                <Line dataKey="expected_total_cost" name="total" stroke="#0f172a" dot={false} strokeWidth={2} />
                <Line dataKey="fraud_exposure" name="fraud missed" stroke="#e11d48" dot={false} />
                <Line dataKey="false_positive_cost" name="customer friction" stroke="#f59e0b" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
      <p className="mt-4 text-xs text-slate-500">{c.disclaimer}</p>
    </>
  );
}
