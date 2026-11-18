import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Clock, History, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Badge, Button, Card, Empty, ErrorNote, Field, Modal, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatINR, formatTime, humanize } from "../lib/format";
import { describeWindow, diffRules, merchantLabel, optionalAmount } from "../lib/rules";
import { CATEGORIES, WEEKDAYS, type Agent, type Merchant, type Policy, type PolicyVersion, type User } from "../lib/types";

type Draft = Omit<Policy, "id" | "version" | "updated_at" | "updated_by">;
type LimitRow = { key: string; amount: number | null };

const blank = (userId = 0, agentId = 0): Draft => ({
  user_id: userId, agent_id: agentId, daily_limit: 100_000, max_transaction: 60_000, approval_threshold: 30_000,
  allowed_categories: ["electronics", "books", "travel"], blocked_categories: ["gambling", "financial_products"],
  allowed_merchants: null, blocked_merchants: null, is_active: true,
  weekly_limit: null, monthly_limit: null, category_limits: null, merchant_limits: null,
  allowed_from: null, allowed_until: null, allowed_days: null,
});

const toDraft = (p: Policy): Draft => {
  const { id: _id, version: _v, updated_at: _u, updated_by: _b, ...rest } = p;
  return rest;
};

export function Policies() {
  const { can } = useAuth();
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => api<Policy[]>("/v1/policies") });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/v1/users") });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/v1/agents") });
  const merchants = useQuery({ queryKey: ["merchants"], queryFn: () => api<Merchant[]>("/v1/merchants") });
  const [editing, setEditing] = useState<Draft | null>(null);
  const [history, setHistory] = useState<Policy | null>(null);

  const userName = (id: number) => users.data?.find((u) => u.id === id)?.name ?? `User ${id}`;
  const agentName = (id: number) => agents.data?.find((a) => a.id === id)?.name ?? `Agent ${id}`;
  const visible = policies.data?.filter((p) => users.data?.some((u) => u.id === p.user_id)) ?? [];

  return (
    <>
      <PageHeader
        title="Policies"
        description="What each agent may spend on behalf of each user. An agent with no policy for a user is always denied. Every change is kept as a numbered version."
        actions={can("admin") && <Button icon={<Plus className="size-4" />} onClick={() => setEditing(blank(users.data?.[0]?.id, agents.data?.[0]?.id))}>New policy</Button>}
      />
      {policies.isLoading ? <Spinner /> : !visible.length ? <Card><Empty title="No policies">Create one to let an agent spend for a user.</Empty></Card> : (
        <div className="grid gap-4 md:grid-cols-2">
          {visible.map((p) => <PolicySummary key={p.id} p={p} agent={agentName(p.agent_id)} user={userName(p.user_id)}
            merchants={merchants.data ?? []} canEdit={can("admin")} onEdit={() => setEditing(toDraft(p))} onHistory={() => setHistory(p)} />)}
        </div>
      )}
      {editing && <PolicyEditor draft={editing} users={users.data ?? []} agents={agents.data ?? []} merchants={merchants.data ?? []} onClose={() => setEditing(null)} />}
      {history && <PolicyHistory policy={history} title={`${agentName(history.agent_id)} for ${userName(history.user_id)}`} merchants={merchants.data ?? []} onClose={() => setHistory(null)} />}
    </>
  );
}

function PolicySummary({ p, agent, user, merchants, canEdit, onEdit, onHistory }: {
  p: Policy; agent: string; user: string; merchants: Merchant[]; canEdit: boolean; onEdit: () => void; onHistory: () => void;
}) {
  const window = describeWindow(p);
  const scoped = [
    ...Object.entries(p.category_limits ?? {}).map(([c, v]) => `${humanize(c)} ≤ ${formatINR(v)}/day`),
    ...Object.entries(p.merchant_limits ?? {}).map(([m, v]) => `${merchantLabel(m, merchants)} ≤ ${formatINR(v)}/day`),
  ];
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-900">{agent}</div>
          <div className="text-sm text-slate-500">spending for {user}</div>
        </div>
        <div className="flex items-center gap-1.5">
          {!p.is_active && <Badge className="bg-slate-100 text-slate-600 ring-slate-500/20">Paused</Badge>}
          <Button size="sm" variant="ghost" icon={<History className="size-3.5" />} onClick={onHistory} title="Version history">v{p.version}</Button>
          {canEdit && <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={onEdit}>Edit</Button>}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <Limit label="Per day" value={p.daily_limit} />
        <Limit label="Per payment" value={p.max_transaction} />
        <Limit label="Ask above" value={p.approval_threshold} />
        {p.weekly_limit != null && <Limit label="Per week" value={p.weekly_limit} />}
        {p.monthly_limit != null && <Limit label="Per month" value={p.monthly_limit} />}
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {p.allowed_categories.map((c) => <Badge key={c} className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">{humanize(c)}</Badge>)}
        {p.blocked_categories.map((c) => <Badge key={c} className="bg-rose-50 text-rose-700 ring-rose-600/20 line-through decoration-rose-400">{humanize(c)}</Badge>)}
      </div>
      {(scoped.length > 0 || window) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {scoped.map((s) => <Badge key={s} className="bg-amber-50 text-amber-800 ring-amber-600/20">{s}</Badge>)}
          {window && <Badge className="bg-sky-50 text-sky-800 ring-sky-600/20"><Clock className="size-3" /> {window}</Badge>}
        </div>
      )}
      <div className="mt-3 text-[11px] text-slate-400">Version {p.version} · updated {formatTime(p.updated_at)}{p.updated_by && ` by ${p.updated_by}`}</div>
    </Card>
  );
}

const Limit = ({ label, value }: { label: string; value: number }) => (
  <div className="rounded-lg bg-slate-50 px-3 py-2"><div className="text-[11px] text-slate-500">{label}</div><div className="font-semibold tabular-nums text-slate-900">{formatINR(value)}</div></div>
);

const Section = ({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) => (
  <section className="space-y-2.5 border-t border-slate-100 pt-4">
    <div><div className="text-sm font-medium text-slate-800">{title}</div>{hint && <p className="text-xs text-slate-500">{hint}</p>}</div>
    {children}
  </section>
);

const toRows = (limits: Record<string, number> | null): LimitRow[] => Object.entries(limits ?? {}).map(([key, amount]) => ({ key, amount }));
const fromRows = (rows: LimitRow[]): Record<string, number> | null => {
  const entries = rows.filter((r) => r.key && r.amount != null).map((r) => [r.key, r.amount as number] as const);
  return entries.length ? Object.fromEntries(entries) : null;
};

function PolicyEditor({ draft, users, agents, merchants, onClose }: {
  draft: Draft; users: User[]; agents: Agent[]; merchants: Merchant[]; onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Draft>(draft);
  const [categoryRows, setCategoryRows] = useState<LimitRow[]>(toRows(draft.category_limits));
  const [merchantRows, setMerchantRows] = useState<LimitRow[]>(
    toRows(draft.merchant_limits).map((r) => ({ ...r, key: merchantLabel(r.key, merchants) })));
  const [timed, setTimed] = useState(Boolean(draft.allowed_from || draft.allowed_days?.length));
  const save = useMutation({
    mutationFn: () => api<Policy>("/v1/policies", {
      method: "PUT",
      body: {
        ...form,
        category_limits: fromRows(categoryRows),
        merchant_limits: fromRows(merchantRows),
        allowed_from: timed ? form.allowed_from || null : null,
        allowed_until: timed ? form.allowed_until || null : null,
        allowed_days: timed && form.allowed_days?.length ? form.allowed_days : null,
      },
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["policies"] }); onClose(); },
  });
  const set = (patch: Partial<Draft>) => setForm((f) => ({ ...f, ...patch }));
  const cycle = (c: string) => {
    // allowed → blocked → neither → allowed
    if (form.allowed_categories.includes(c)) set({ allowed_categories: form.allowed_categories.filter((x) => x !== c), blocked_categories: [...form.blocked_categories, c] });
    else if (form.blocked_categories.includes(c)) set({ blocked_categories: form.blocked_categories.filter((x) => x !== c) });
    else set({ allowed_categories: [...form.allowed_categories, c] });
  };
  const toggleDay = (d: string) => {
    const days = form.allowed_days ?? [];
    set({ allowed_days: days.includes(d) ? days.filter((x) => x !== d) : WEEKDAYS.filter((x) => x === d || days.includes(x)) });
  };
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const usedCategories = new Set(categoryRows.map((r) => r.key));
  const usedMerchants = new Set(merchantRows.map((r) => r.key));

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
          <Field label="Weekly limit (₹)" hint="Optional, Mon–Sun"><input className="input tabular-nums" type="number" min={0} placeholder="No limit" value={form.weekly_limit ?? ""} onChange={(e) => set({ weekly_limit: optionalAmount(e.target.value) })} /></Field>
          <Field label="Monthly limit (₹)" hint="Optional, calendar month"><input className="input tabular-nums" type="number" min={0} placeholder="No limit" value={form.monthly_limit ?? ""} onChange={(e) => set({ monthly_limit: optionalAmount(e.target.value) })} /></Field>
        </div>
        <p className="-mt-2 text-xs text-slate-500">Limits count only this agent's spending. A cap across all of the user's agents is set on the user (Users &amp; merchants).</p>

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

        <Section title="Daily limits per category" hint="Checked against the merchant's registered category, so relabelling a purchase can't get around it.">
          <LimitRows rows={categoryRows} setRows={setCategoryRows}
            options={CATEGORIES.filter((c) => !usedCategories.has(c)).map((c) => ({ value: c, label: humanize(c) }))}
            label={(k) => humanize(k)} addLabel="Add category limit" />
        </Section>

        <Section title="Daily limits per merchant">
          <LimitRows rows={merchantRows} setRows={setMerchantRows}
            options={merchants.filter((m) => !usedMerchants.has(m.name)).map((m) => ({ value: m.name, label: m.name }))}
            label={(k) => k} addLabel="Add merchant limit" />
        </Section>

        <Section title="When this agent may pay" hint="Local time in the spend time zone. A window like 22:00–06:00 runs past midnight. Reviewers can still approve outside the window.">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={timed} onChange={(e) => setTimed(e.target.checked)} className="size-4 rounded accent-brand-600" />
            Only at certain times
          </label>
          {timed && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="From"><input className="input" type="time" value={form.allowed_from ?? ""} onChange={(e) => set({ allowed_from: e.target.value || null })} /></Field>
                <Field label="Until (not including)"><input className="input" type="time" value={form.allowed_until ?? ""} onChange={(e) => set({ allowed_until: e.target.value || null })} /></Field>
              </div>
              <div>
                <div className="label">Days (none selected = every day)</div>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((d) => (
                    <button type="button" key={d} onClick={() => toggleDay(d)} className={clsx("w-12 rounded-md py-1 text-xs font-medium ring-1 ring-inset transition",
                      form.allowed_days?.includes(d) ? "bg-sky-50 text-sky-800 ring-sky-600/30" : "bg-white text-slate-500 ring-slate-300")}>
                      {humanize(d)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </Section>

        <label className="flex items-center gap-2 border-t border-slate-100 pt-4 text-sm text-slate-700">
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

function LimitRows({ rows, setRows, options, label, addLabel }: {
  rows: LimitRow[]; setRows: (r: LimitRow[]) => void; options: { value: string; label: string }[];
  label: (key: string) => string; addLabel: string;
}) {
  const update = (i: number, patch: Partial<LimitRow>) => setRows(rows.map((r, j) => (i === j ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <select className="input flex-1" value={r.key} onChange={(e) => update(i, { key: e.target.value })}>
            {r.key && <option value={r.key}>{label(r.key)}</option>}
            {!r.key && <option value="">Choose…</option>}
            {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <input className="input w-36 tabular-nums" type="number" min={0} placeholder="₹ per day" value={r.amount ?? ""}
            onChange={(e) => update(i, { amount: optionalAmount(e.target.value) })} />
          <Button type="button" size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} aria-label="Remove"
            onClick={() => setRows(rows.filter((_, j) => j !== i))} />
        </div>
      ))}
      {options.length > 0 && (
        <Button type="button" size="sm" variant="secondary" icon={<Plus className="size-3.5" />}
          onClick={() => setRows([...rows, { key: options[0].value, amount: null }])}>{addLabel}</Button>
      )}
    </div>
  );
}

function PolicyHistory({ policy, title, merchants, onClose }: { policy: Policy; title: string; merchants: Merchant[]; onClose: () => void }) {
  const versions = useQuery({
    queryKey: ["policy-versions", policy.user_id, policy.agent_id, policy.version],
    queryFn: () => api<PolicyVersion[]>(`/v1/policies/${policy.user_id}/${policy.agent_id}/versions`),
  });
  const list = versions.data ?? [];
  return (
    <Modal open title={`Policy history · ${title}`} onClose={onClose} wide>
      {versions.isLoading ? <Spinner /> : versions.error ? <ErrorNote error={versions.error} /> : (
        <ol className="space-y-3">
          {list.map((v, i) => {
            const changes = diffRules(list[i + 1]?.rules ?? null, v.rules, merchants);
            return (
              <li key={v.version} className="rounded-lg border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge className={i === 0 ? "bg-brand-50 text-brand-700 ring-brand-600/20" : undefined}>v{v.version}{i === 0 && " · current"}</Badge>
                  <span className="text-slate-500">{formatTime(v.created_at)}{v.updated_by && ` by ${v.updated_by}`}</span>
                </div>
                <ul className="mt-2 space-y-0.5 text-xs text-slate-700">
                  {(changes.length ? changes : ["No rule changes"]).map((c) => <li key={c}>{c}</li>)}
                </ul>
              </li>
            );
          })}
        </ol>
      )}
      <p className="mt-4 text-xs text-slate-500">Each payment records the version that decided it, so past decisions can be explained with the rules in force at the time.</p>
    </Modal>
  );
}
