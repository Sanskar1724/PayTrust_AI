import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, Play, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorNote, Field, PageHeader, Spinner, Stat } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatPct, formatTime } from "../lib/format";
import { useLive } from "../lib/live";
import type { ArenaRun, ArenaStats } from "../lib/types";

interface Catalog {
  scenarios: { key: string; title: string; weights: Record<string, number> }[];
  personas: { key: string; title: string; intent: string; description: string; expectation: string }[];
}

export function Arena() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const live = useLive();
  const catalog = useQuery({ queryKey: ["arena", "catalog"], queryFn: () => api<Catalog>("/v1/arena/scenarios") });
  const runs = useQuery({ queryKey: ["arena", "runs"], queryFn: () => api<ArenaRun[]>("/v1/arena/runs") });
  const [scenario, setScenario] = useState("mixed");
  const [requests, setRequests] = useState(120);
  const [concurrency, setConcurrency] = useState(6);
  const [selected, setSelected] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: () => api<ArenaRun>("/v1/arena/runs", { method: "POST", body: { scenario, requests, concurrency } }),
    onSuccess: (run) => {
      setSelected(run.id);
      queryClient.invalidateQueries({ queryKey: ["arena", "runs"] });
    },
  });

  // Prefer the live stream for the running run; fall back to polling if the stream is down.
  const running = runs.data?.find((r) => r.status === "RUNNING");
  useEffect(() => {
    if (!running || live.connected) return;
    const t = window.setInterval(() => queryClient.invalidateQueries({ queryKey: ["arena", "runs"] }), 2000);
    return () => window.clearInterval(t);
  }, [running, live.connected, queryClient]);

  const base = runs.data?.find((r) => r.id === selected) ?? runs.data?.[0];
  const current = base && live.arena?.id === base.id ? { ...base, ...live.arena, stats: live.arena.stats ?? base.stats } : base;

  return (
    <>
      <PageHeader
        title="Agent Arena"
        description="Simulated AI agents — honest and malicious — send real payments through the API. Each request knows whether it should have been allowed, so the scorecard shows how well PayTrust protects users."
      />
      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <div className="space-y-6">
          <Card title="New run">
            <div className="space-y-4">
              <Field label="Scenario">
                <select className="input" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  {catalog.data?.scenarios.map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Requests"><input className="input" type="number" min={1} max={2000} value={requests} onChange={(e) => setRequests(Number(e.target.value))} /></Field>
                <Field label="Parallel agents"><input className="input" type="number" min={1} max={32} value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))} /></Field>
              </div>
              <ErrorNote error={start.error} />
              <Button className="w-full" icon={<Play className="size-4" />} loading={start.isPending} disabled={!can("reviewer") || !!running} onClick={() => start.mutate()}>
                {running ? "A run is in progress" : "Start simulation"}
              </Button>
              <p className="text-xs text-slate-500">Each run creates its own payers with a standard policy (₹1,00,000/day, ₹60,000 max, approval above ₹30,000) and its own API keys, which are revoked when the run ends.</p>
            </div>
          </Card>
          <Card title="Who's in the arena">
            <ul className="space-y-3">
              {catalog.data?.personas.map((p) => (
                <li key={p.key} className="text-sm">
                  <div className="flex items-center gap-2">
                    {p.intent === "malicious" ? <ShieldAlert className="size-4 text-rose-500" /> : <ShieldCheck className="size-4 text-emerald-500" />}
                    <span className="font-medium text-slate-800">{p.title}</span>
                  </div>
                  <div className="ml-6 text-xs text-slate-500">{p.description}</div>
                  <div className="ml-6 text-xs text-slate-600">Expected: <span className="font-medium">{p.expectation}</span></div>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="space-y-6">
          {runs.isLoading ? <Spinner /> : !current ? (
            <Card><Empty title="No runs yet">Start a simulation to see how PayTrust handles honest and malicious agents.</Empty></Card>
          ) : (
            <Scorecard run={current} />
          )}
          {!!runs.data?.length && (
            <Card title="Run history" padded={false}>
              <table className="w-full text-sm">
                <thead className="table-head"><tr><th className="px-5 py-2.5">Started</th><th className="px-3 py-2.5">Scenario</th><th className="px-3 py-2.5">Requests</th><th className="px-3 py-2.5">Accuracy</th><th className="px-5 py-2.5">Status</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.data.map((r) => (
                    <tr key={r.id} onClick={() => setSelected(r.id)} className={clsx("cursor-pointer hover:bg-slate-50", current?.id === r.id && "bg-brand-50/50")}>
                      <td className="px-5 py-2.5 text-xs text-slate-600">{formatTime(r.started_at)}</td>
                      <td className="px-3 py-2.5">{r.scenario}</td>
                      <td className="px-3 py-2.5 tabular-nums">{r.stats.completed ?? 0}/{r.params.requests}</td>
                      <td className="px-3 py-2.5 tabular-nums">{r.stats.accuracy != null ? formatPct(r.stats.accuracy, 1) : "—"}</td>
                      <td className="px-5 py-2.5"><RunStatus status={r.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function RunStatus({ status }: { status: ArenaRun["status"] }) {
  const cls = status === "COMPLETED" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : status === "FAILED" ? "bg-rose-50 text-rose-700 ring-rose-600/20" : "bg-brand-50 text-brand-700 ring-brand-500/30";
  return <Badge className={cls}>{status === "RUNNING" ? "Running…" : status.toLowerCase()}</Badge>;
}

function Scorecard({ run }: { run: Pick<ArenaRun, "id" | "status" | "stats" | "error"> & Partial<ArenaRun> }) {
  const s = run.stats as Partial<ArenaStats>;
  const progress = s.planned ? (s.completed ?? 0) / s.planned : 0;
  return (
    <Card title={<span className="flex items-center gap-2">Scorecard <RunStatus status={run.status} /></span>}
      action={<span className="text-xs text-slate-500">{run.scenario} · {run.params?.concurrency} parallel</span>}>
      {run.error && <ErrorNote error={new Error(run.error)} />}
      {run.status === "RUNNING" && (
        <div className="mb-5">
          <div className="mb-1 flex justify-between text-xs text-slate-500"><span>{s.completed ?? 0} of {s.planned ?? "…"} requests</span><span>{formatPct(progress)}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${progress * 100}%` }} /></div>
        </div>
      )}
      {s.completed ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Correct decisions" value={formatPct(s.accuracy, 1)} hint={`${s.correct} of ${s.completed}`} tone={s.accuracy === 1 ? "good" : undefined} />
            <Stat label="Attacks caught" value={`${s.malicious?.caught}/${s.malicious?.total}`} tone={s.malicious?.missed ? "bad" : "good"} hint={s.malicious?.missed ? `${s.malicious.missed} slipped through` : "none slipped through"} />
            <Stat label="Honest payments blocked" value={`${s.legit?.blocked}/${s.legit?.total}`} tone={s.legit?.blocked ? "bad" : "good"} hint={`${s.legit?.allowed} allowed straight through`} />
            <Stat label="Throughput" value={`${s.throughput_rps} rps`} hint={`server p95 ${s.latency_ms?.server_p95} ms · client p95 ${s.latency_ms?.client_p95} ms`} />
          </div>
          <div className="mt-6 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="table-head"><tr><th className="px-3 py-2">Persona</th><th className="px-3 py-2">Expected</th><th className="px-3 py-2">Got</th><th className="px-3 py-2 text-right">Correct</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {Object.entries(s.personas ?? {}).map(([key, p]) => (
                  <tr key={key}>
                    <td className="px-3 py-2.5"><div className="flex items-center gap-2">{p.intent === "malicious" ? <ShieldAlert className="size-4 text-rose-500" /> : <ShieldCheck className="size-4 text-emerald-500" />}<span className="font-medium">{p.title}</span></div></td>
                    <td className="px-3 py-2.5 text-xs text-slate-500">{p.expectation}</td>
                    <td className="px-3 py-2.5 text-xs">{Object.entries(p.decisions).map(([d, n]) => `${d === "ASK_USER" ? "ASK" : d} ${n}`).join(" · ")}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      <span className={clsx("font-medium", p.correct === p.requests ? "text-emerald-700" : "text-rose-700")}>{p.correct}/{p.requests}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!!s.mistakes?.length && (
            <div className="mt-6">
              <div className="label">Decisions that didn't match expectations</div>
              <ul className="space-y-1 text-xs">
                {s.mistakes.map((m) => (
                  <li key={m.request_id} className="flex flex-wrap gap-2">
                    <Link to={`/payments/${m.request_id}`} className="font-mono text-brand-700 hover:underline">{m.request_id}</Link>
                    <span className="text-slate-600">{m.persona}: got {m.decision ?? `HTTP ${m.status_code}`}, expected {m.expected.join(" or ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {run.status === "COMPLETED" && !s.mistakes?.length && (
            <div className="mt-6 flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="size-4" /> Every decision matched its expected outcome.</div>
          )}
        </>
      ) : run.status === "RUNNING" ? <Spinner label="Agents are warming up" /> : null}
    </Card>
  );
}
