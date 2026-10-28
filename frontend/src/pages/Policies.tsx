import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Pencil, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, Empty, ErrorNote, Field, Modal, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatINR, formatTime, humanize } from "../lib/format";
import { CATEGORIES, type Agent, type Policy, type User } from "../lib/types";

type Draft = Omit<Policy, "id" | "updated_at" | "updated_by">;

const blank = (userId = 0, agentId = 0): Draft => ({
  user_id: userId, agent_id: agentId, daily_limit: 100_000, max_transaction: 60_000, approval_threshold: 30_000,
  allowed_categories: ["electronics", "books", "travel"], blocked_categories: ["gambling", "financial_products"],
  allowed_merchants: null, blocked_merchants: null, is_active: true,
});

export function Policies() {
  const { can } = useAuth();
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => api<Policy[]>("/v1/policies") });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/v1/users") });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/v1/agents") });
  const [editing, setEditing] = useState<Draft | null>(null);

  const userName = (id: number) => users.data?.find((u) => u.id === id)?.name ?? `User ${id}`;
  const agentName = (id: number) => agents.data?.find((a) => a.id === id)?.name ?? `Agent ${id}`;
  const visible = policies.data?.filter((p) => users.data?.some((u) => u.id === p.user_id)) ?? [];

  return (
    <>
      <PageHeader
        title="Policies"
        description="What each agent may spend on behalf of each user. An agent with no policy for a user is always denied."
        actions={can("admin") && <Button icon={<Plus className="size-4" />} onClick={() => setEditing(blank(users.data?.[0]?.id, agents.data?.[0]?.id))}>New policy</Button>}
      />
      {policies.isLoading ? <Spinner /> : !visible.length ? <Card><Empty title="No policies">Create one to let an agent spend for a user.</Empty></Card> : (
        <div className="grid gap-4 md:grid-cols-2">
          {visible.map((p) => (
            <Card key={p.id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold text-slate-900">{agentName(p.agent_id)}</div>
                  <div className="text-sm text-slate-500">spending for {userName(p.user_id)}</div>
                </div>
                <div className="flex items-center gap-2">
                  {!p.is_active && <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">Paused</Badge>}
                  {can("admin") && <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing({ ...p })}>Edit</Button>}
                </div>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
                <Limit label="Per day" value={p.daily_limit} />
                <Limit label="Per payment" value={p.max_transaction} />
                <Limit label="Ask above" value={p.approval_threshold} />
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {p.allowed_categories.map((c) => <Badge key={c} className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">{humanize(c)}</Badge>)}
                {p.blocked_categories.map((c) => <Badge key={c} className="bg-rose-50 text-rose-700 ring-rose-600/20 line-through decoration-rose-400">{humanize(c)}</Badge>)}
              </div>
              <div className="mt-3 text-[11px] text-slate-400">Updated {formatTime(p.updated_at)}{p.updated_by && ` by ${p.updated_by}`}</div>
            </Card>
          ))}
        </div>
      )}
      {editing && <PolicyEditor draft={editing} users={users.data ?? []} agents={agents.data ?? []} onClose={() => setEditing(null)} />}
    </>
  );
}

const Limit = ({ label, value }: { label: string; value: number }) => (
  <div className="rounded-lg bg-slate-50 px-3 py-2"><div className="text-[11px] text-slate-500">{label}</div><div className="font-semibold tabular-nums text-slate-900">{formatINR(value)}</div></div>
);

function PolicyEditor({ draft, users, agents, onClose }: { draft: Draft; users: User[]; agents: Agent[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Draft>(draft);
  const save = useMutation({
    mutationFn: () => api<Policy>("/v1/policies", { method: "PUT", body: form }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["policies"] }); onClose(); },
  });
  const set = (patch: Partial<Draft>) => setForm((f) => ({ ...f, ...patch }));
  const cycle = (c: string) => {
    // allowed → blocked → neither → allowed
    if (form.allowed_categories.includes(c)) set({ allowed_categories: form.allowed_categories.filter((x) => x !== c), blocked_categories: [...form.blocked_categories, c] });
    else if (form.blocked_categories.includes(c)) set({ blocked_categories: form.blocked_categories.filter((x) => x !== c) });
    else set({ allowed_categories: [...form.allowed_categories, c] });
  };
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Modal open title="Spending policy" onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="User"><select className="input" value={form.user_id} onChange={(e) => set({ user_id: Number(e.target.value) })}>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
          <Field label="Agent"><select className="input" value={form.agent_id} onChange={(e) => set({ agent_id: Number(e.target.value) })}>{agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Daily limit (₹)"><input className="input tabular-nums" type="number" min={0} value={form.daily_limit} onChange={(e) => set({ daily_limit: Number(e.target.value) })} /></Field>
          <Field label="Max per payment (₹)"><input className="input tabular-nums" type="number" min={0} value={form.max_transaction} onChange={(e) => set({ max_transaction: Number(e.target.value) })} /></Field>
          <Field label="Ask user above (₹)"><input className="input tabular-nums" type="number" min={0} value={form.approval_threshold} onChange={(e) => set({ approval_threshold: Number(e.target.value) })} /></Field>
        </div>
        <div>
          <div className="label">Categories — click to cycle allowed → blocked → not set</div>
          <div className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => {
              const state = form.allowed_categories.includes(c) ? "allowed" : form.blocked_categories.includes(c) ? "blocked" : "none";
              return (
                <button type="button" key={c} onClick={() => cycle(c)} className={clsx("rounded-md px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition",
                  state === "allowed" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/30" : state === "blocked" ? "bg-rose-50 text-rose-700 ring-rose-600/30 line-through" : "bg-white text-slate-500 ring-slate-300")}>
                  {humanize(c)}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-xs text-slate-500">If any category is allowed, everything not allowed is rejected.</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} className="size-4 rounded accent-brand-600" />
          Policy active (pausing it denies every payment from this agent for this user)
        </label>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>Save policy</Button>
        </div>
      </form>
    </Modal>
  );
}
