import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Shuffle } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AiCard, DecisionHero, PolicyCard, RiskCard, SimulationCard } from "../components/Evidence";
import { Button, Card, ErrorNote, Field, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { humanize } from "../lib/format";
import { CATEGORIES, type Agent, type Merchant, type Payment, type User } from "../lib/types";

const newId = () => `play_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;

const PRESETS = [
  { label: "Normal purchase", merchant: "TechMart Electronics", amount: 8_500, category: "electronics" },
  { label: "Large purchase", merchant: "TechMart Electronics", amount: 45_000, category: "electronics" },
  { label: "Over the max", merchant: "TravelEase", amount: 75_000, category: "travel" },
  { label: "Gambling", merchant: "BetZone", amount: 2_000, category: "gambling" },
  { label: "Mislabelled", merchant: "BetZone", amount: 2_000, category: "electronics" },
];

export function Playground() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/v1/users") });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/v1/agents") });
  const merchants = useQuery({ queryKey: ["merchants"], queryFn: () => api<Merchant[]>("/v1/merchants") });

  const [form, setForm] = useState({ request_id: newId(), user_id: 0, agent_id: 0, merchant_id: 0, amount: 8_500, category: "electronics", description: "", agent_reason: "" });
  const [resultId, setResultId] = useState<string | null>(null);

  useEffect(() => {
    setForm((f) => ({
      ...f,
      user_id: f.user_id || users.data?.[0]?.id || 0,
      agent_id: f.agent_id || agents.data?.find((a) => !a.name.startsWith("Arena"))?.id || 0,
      merchant_id: f.merchant_id || merchants.data?.[0]?.id || 0,
    }));
  }, [users.data, agents.data, merchants.data]);

  const merchant = useMemo(() => merchants.data?.find((m) => m.id === form.merchant_id), [merchants.data, form.merchant_id]);
  const evaluate = useMutation({
    mutationFn: () => api<Payment>("/v1/playground/evaluate", {
      method: "POST",
      body: { ...form, merchant_name: merchant?.name ?? "", description: form.description || null, agent_reason: form.agent_reason || null },
    }),
    onSuccess: (p) => {
      queryClient.setQueryData(["payment", p.request_id], p);
      setResultId(p.request_id);
      setForm((f) => ({ ...f, request_id: newId() }));
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
  // Follows the stored payment: the AI explanation and order are added in the background after the decision.
  const resultQuery = useQuery({
    queryKey: ["payment", resultId],
    queryFn: () => api<Payment>(`/v1/payments/${resultId}`),
    enabled: !!resultId,
    refetchInterval: (q) => (q.state.data?.status === "PENDING_APPROVAL" && !q.state.data.ai ? 1500 : false),
  });
  const result = resultQuery.data ?? null;
  const investigate = useMutation({
    mutationFn: () => api<Payment>(`/v1/payments/${resultId}/investigate`, { method: "POST" }),
    onSuccess: (p) => queryClient.setQueryData(["payment", p.request_id], p),
  });

  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));
  const submit = (e: FormEvent) => { e.preventDefault(); evaluate.mutate(); };
  const preset = (p: (typeof PRESETS)[number]) => {
    const m = merchants.data?.find((x) => x.name === p.merchant);
    set({ amount: p.amount, category: p.category, merchant_id: m?.id ?? form.merchant_id });
  };

  return (
    <>
      <PageHeader title="Playground" description="Submit a payment as any agent and see exactly how PayTrust decides. Uses the same pipeline and limits as real agent traffic." />
      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <Card title="Payment request">
          <form onSubmit={submit} className="space-y-4">
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button type="button" key={p.label} onClick={() => preset(p)} className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:border-brand-500 hover:text-brand-700">{p.label}</button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="User (payer)">
                <select className="input" value={form.user_id} onChange={(e) => set({ user_id: Number(e.target.value) })}>
                  {users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
              </Field>
              <Field label="Agent">
                <select className="input" value={form.agent_id} onChange={(e) => set({ agent_id: Number(e.target.value) })}>
                  {agents.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </Field>
            </div>
            <Field label="Merchant" hint={merchant && `Registered as ${humanize(merchant.category ?? "unknown")}${merchant.risk_tier === "high" ? " · high-risk tier" : ""}`}>
              <select className="input" value={form.merchant_id} onChange={(e) => set({ merchant_id: Number(e.target.value) })}>
                {merchants.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Amount (INR)">
                <input className="input tabular-nums" type="number" min={1} step={1} value={form.amount} onChange={(e) => set({ amount: Number(e.target.value) })} required />
              </Field>
              <Field label="Category (agent's claim)">
                <select className="input" value={form.category} onChange={(e) => set({ category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
                </select>
              </Field>
            </div>
            <Field label="Description"><input className="input" value={form.description} onChange={(e) => set({ description: e.target.value })} maxLength={500} placeholder="Laptop, 16 GB RAM" /></Field>
            <Field label="Agent's reason"><input className="input" value={form.agent_reason} onChange={(e) => set({ agent_reason: e.target.value })} maxLength={500} placeholder="User asked for a laptop under ₹50k" /></Field>
            <Field label="Request id" hint="Idempotency key — resend the same id to get the stored decision back.">
              <div className="flex gap-2">
                <input className="input font-mono text-xs" value={form.request_id} onChange={(e) => set({ request_id: e.target.value })} />
                <Button type="button" variant="secondary" onClick={() => set({ request_id: newId() })} title="New id"><Shuffle className="size-4" /></Button>
              </div>
            </Field>
            <ErrorNote error={evaluate.error} />
            <Button type="submit" className="w-full" icon={<Send className="size-4" />} loading={evaluate.isPending} disabled={!can("reviewer")}>
              {can("reviewer") ? "Evaluate payment" : "Reviewer role required"}
            </Button>
          </form>
        </Card>
        <div className="space-y-6">
          {!result ? (
            <Card><div className="py-16 text-center text-sm text-slate-500">The decision and its full evidence will appear here.</div></Card>
          ) : (
            <>
              <DecisionHero p={result} />
              <div className="grid gap-6 xl:grid-cols-2">
                <PolicyCard p={result} />
                <RiskCard p={result} />
                <AiCard p={result} canRun busy={investigate.isPending} onInvestigate={() => investigate.mutate()} />
                <SimulationCard p={result} />
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
