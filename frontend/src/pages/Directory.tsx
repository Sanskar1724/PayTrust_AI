import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, Empty, ErrorNote, Field, Modal, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatINR, formatTime, humanize } from "../lib/format";
import { optionalAmount } from "../lib/rules";
import { CATEGORIES, type Merchant, type User } from "../lib/types";

export function Directory() {
  const { can } = useAuth();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/v1/users") });
  const merchants = useQuery({ queryKey: ["merchants"], queryFn: () => api<Merchant[]>("/v1/merchants") });
  const [modal, setModal] = useState<null | "user" | "merchant">(null);
  const [budgetFor, setBudgetFor] = useState<User | null>(null);

  return (
    <>
      <PageHeader title="Users & merchants" description="Payers that agents act for, and the merchants they pay. A merchant's registered category is checked against policy even if the agent claims a different one." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Users (payers)" padded={false} action={can("admin") && <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => setModal("user")}>Add user</Button>}>
          {users.isLoading ? <Spinner /> : !users.data?.length ? <Empty title="No users" /> : (
            <table className="w-full text-sm">
              <thead className="table-head"><tr><th className="px-5 py-2.5">ID</th><th className="px-3 py-2.5">Name</th><th className="px-3 py-2.5">Budget (all agents)</th><th className="px-5 py-2.5">Added</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {users.data.map((u) => (
                  <tr key={u.id} className="align-top">
                    <td className="px-5 py-2.5 font-mono text-xs">{u.id}</td>
                    <td className="px-3 py-2.5"><div>{u.name}</div><div className="text-xs text-slate-500">{u.email}</div>{u.external_ref && <div className="font-mono text-[11px] text-slate-400">{u.external_ref}</div>}</td>
                    <td className="px-3 py-2.5 text-xs">
                      <BudgetSummary u={u} />
                      {can("admin") && <Button size="sm" variant="ghost" className="-ml-2 mt-1" icon={<Pencil className="size-3" />} onClick={() => setBudgetFor(u)}>Edit</Button>}
                    </td>
                    <td className="px-5 py-2.5 text-xs text-slate-500">{formatTime(u.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Merchants" padded={false} action={can("admin") && <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => setModal("merchant")}>Add merchant</Button>}>
          {merchants.isLoading ? <Spinner /> : !merchants.data?.length ? <Empty title="No merchants" /> : (
            <table className="w-full text-sm">
              <thead className="table-head"><tr><th className="px-5 py-2.5">ID</th><th className="px-3 py-2.5">Name</th><th className="px-3 py-2.5">Category</th><th className="px-5 py-2.5">Tier</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {merchants.data.map((m) => (
                  <tr key={m.id}>
                    <td className="px-5 py-2.5 font-mono text-xs">{m.id}</td><td className="px-3 py-2.5">{m.name}</td>
                    <td className="px-3 py-2.5">{m.category ? humanize(m.category) : "—"}</td>
                    <td className="px-5 py-2.5">{m.risk_tier === "high" ? <Badge className="bg-rose-50 text-rose-700 ring-rose-600/20">High risk</Badge> : <Badge>Standard</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      {modal === "user" && <UserForm onClose={() => setModal(null)} />}
      {modal === "merchant" && <MerchantForm onClose={() => setModal(null)} />}
      {budgetFor && <BudgetForm user={budgetFor} onClose={() => setBudgetFor(null)} />}
    </>
  );
}

function BudgetSummary({ u }: { u: User }) {
  const caps = [["day", u.daily_budget], ["week", u.weekly_budget], ["month", u.monthly_budget]] as const;
  const set = caps.filter(([, v]) => v != null);
  if (!set.length) return <span className="text-slate-400">No overall cap</span>;
  return <div className="space-y-0.5 tabular-nums text-slate-700">{set.map(([p, v]) => <div key={p}>{formatINR(v)} / {p}</div>)}</div>;
}

function BudgetForm({ user, onClose }: { user: User; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ daily_budget: user.daily_budget, weekly_budget: user.weekly_budget, monthly_budget: user.monthly_budget });
  const save = useMutation({
    mutationFn: () => api(`/v1/users/${user.id}`, { method: "PATCH", body: form }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); onClose(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const field = (key: keyof typeof form, label: string) => (
    <Field label={label}><input className="input tabular-nums" type="number" min={0} placeholder="No cap" value={form[key] ?? ""}
      onChange={(e) => setForm({ ...form, [key]: optionalAmount(e.target.value) })} /></Field>
  );
  return (
    <Modal open title={`Overall budget · ${user.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-600">Caps what <b>all</b> of this user's agents may spend together. Each agent's own policy limits still apply. Leave a field empty for no cap.</p>
        <div className="grid grid-cols-3 gap-3">
          {field("daily_budget", "Per day (₹)")}
          {field("weekly_budget", "Per week (₹)")}
          {field("monthly_budget", "Per month (₹)")}
        </div>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Save budget</Button></div>
      </form>
    </Modal>
  );
}

function UserForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", external_ref: "" });
  const save = useMutation({
    mutationFn: () => api("/v1/users", { method: "POST", body: { name: form.name, email: form.email || null, external_ref: form.external_ref || null } }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); onClose(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open title="Add user" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus /></Field>
        <Field label="Email"><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="External reference" hint="Your system's id for this user (unique)."><input className="input" value={form.external_ref} onChange={(e) => setForm({ ...form, external_ref: e.target.value })} /></Field>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Add user</Button></div>
      </form>
    </Modal>
  );
}

function MerchantForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name: "", category: "electronics", risk_tier: "standard" });
  const save = useMutation({
    mutationFn: () => api("/v1/merchants", { method: "POST", body: form }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["merchants"] }); onClose(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open title="Add merchant" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Registered category"><select className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</select></Field>
          <Field label="Risk tier"><select className="input" value={form.risk_tier} onChange={(e) => setForm({ ...form, risk_tier: e.target.value })}><option value="standard">Standard</option><option value="high">High</option></select></Field>
        </div>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Add merchant</Button></div>
      </form>
    </Modal>
  );
}
