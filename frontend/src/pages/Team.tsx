import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, ErrorNote, Field, Modal, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatTime } from "../lib/format";
import type { Operator, Role } from "../lib/types";

const ROLE_HELP: Record<Role, string> = {
  viewer: "Can see everything, change nothing",
  reviewer: "Can approve/reject payments, use the Playground and Arena",
  admin: "Full access: policies, agents, keys, team",
};

export function Team() {
  const { operator: me } = useAuth();
  const queryClient = useQueryClient();
  const team = useQuery({ queryKey: ["operators"], queryFn: () => api<Operator[]>("/v1/operators") });
  const [adding, setAdding] = useState(false);
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<Pick<Operator, "role" | "is_active">> }) => api(`/v1/operators/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["operators"] }),
  });

  return (
    <>
      <PageHeader title="Team" description="People who can sign in to this console." actions={<Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add member</Button>} />
      <ErrorNote error={update.error} />
      <Card padded={false}>
        {team.isLoading ? <Spinner /> : (
          <table className="w-full text-sm">
            <thead className="table-head"><tr><th className="px-5 py-2.5">Member</th><th className="px-3 py-2.5">Role</th><th className="px-3 py-2.5">Last sign-in</th><th className="px-5 py-2.5 text-right">Access</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {team.data?.map((op) => (
                <tr key={op.id}>
                  <td className="px-5 py-3"><div className="font-medium text-slate-900">{op.name}{op.id === me?.id && <span className="ml-1 text-xs text-slate-400">(you)</span>}</div><div className="text-xs text-slate-500">{op.email}</div></td>
                  <td className="px-3 py-3">
                    <select className="input w-auto py-1 text-xs" value={op.role} disabled={op.id === me?.id} onChange={(e) => update.mutate({ id: op.id, patch: { role: e.target.value as Role } })}>
                      {(["viewer", "reviewer", "admin"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-500">{op.last_login_at ? formatTime(op.last_login_at) : "never"}</td>
                  <td className="px-5 py-3 text-right">
                    {op.id === me?.id ? <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">Active</Badge> : (
                      <Button size="sm" variant={op.is_active ? "ghost" : "secondary"} onClick={() => update.mutate({ id: op.id, patch: { is_active: !op.is_active } })}>
                        {op.is_active ? "Deactivate" : "Reactivate"}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {adding && <AddMember onClose={() => setAdding(false)} />}
    </>
  );
}

function AddMember({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", role: "reviewer" as Role, password: "" });
  const save = useMutation({
    mutationFn: () => api("/v1/operators", { method: "POST", body: form }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["operators"] }); onClose(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open title="Add team member" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus /></Field>
        <Field label="Email"><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></Field>
        <Field label="Role" hint={ROLE_HELP[form.role]}>
          <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{(["viewer", "reviewer", "admin"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}</select>
        </Field>
        <Field label="Temporary password" hint="At least 8 characters. Share it securely."><input className="input" type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required autoComplete="new-password" /></Field>
        <ErrorNote error={save.error} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Add member</Button></div>
      </form>
    </Modal>
  );
}
