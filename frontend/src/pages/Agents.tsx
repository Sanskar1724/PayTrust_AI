import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, Empty, ErrorNote, Field, Modal, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatTime, timeAgo } from "../lib/format";
import type { Agent, ApiKey } from "../lib/types";

export function Agents() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/v1/agents") });
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<{ title: string; value: string; note: string } | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<{ agent: Agent; key: ApiKey } | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["agents"] });

  const newKey = useMutation({
    mutationFn: (agent: Agent) => api<ApiKey & { key: string }>(`/v1/agents/${agent.id}/keys`, { method: "POST", body: { name: `key-${new Date().toISOString().slice(0, 10)}` } }),
    onSuccess: (k) => { refresh(); setSecret({ title: "New API key", value: k.key, note: "Send it as the X-API-Key header. It is shown once — PayTrust only stores a hash." }); },
  });
  const revoke = useMutation({
    mutationFn: ({ agent, key }: { agent: Agent; key: ApiKey }) => api(`/v1/agents/${agent.id}/keys/${key.id}`, { method: "DELETE" }),
    onSuccess: () => { refresh(); setConfirmRevoke(null); },
  });
  const toggle = useMutation({
    mutationFn: (agent: Agent) => api(`/v1/agents/${agent.id}`, { method: "PATCH", body: { is_active: !agent.is_active } }),
    onSuccess: refresh,
  });

  const list = agents.data?.filter((a) => !a.name.startsWith("Arena")) ?? [];

  return (
    <>
      <PageHeader
        title="Agents & keys"
        description="AI agents that can request payments. Each agent authenticates with its own API keys; a key can only act as its own agent."
        actions={can("admin") && <Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>New agent</Button>}
      />
      <ErrorNote error={newKey.error ?? toggle.error} />
      {agents.isLoading ? <Spinner /> : !list.length ? <Card><Empty title="No agents yet" /></Card> : (
        <div className="space-y-4">
          {list.map((agent) => {
            const active = agent.keys.filter((k) => !k.revoked_at);
            return (
              <Card key={agent.id}>
                <div className="flex flex-wrap items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-900">{agent.name}</span>
                      <span className="font-mono text-xs text-slate-400">#{agent.id}</span>
                      {agent.is_active ? <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-600/20">Active</Badge> : <Badge>Disabled</Badge>}
                    </div>
                    <div className="mt-0.5 text-sm text-slate-500">{agent.description || "No description"}</div>
                    {agent.callback_url && <div className="mt-1 font-mono text-xs text-slate-500">callback → {agent.callback_url}</div>}
                  </div>
                  {can("admin") && (
                    <div className="flex gap-2">
                      <Button size="sm" variant="secondary" icon={<KeyRound className="size-3.5" />} loading={newKey.isPending && newKey.variables?.id === agent.id} onClick={() => newKey.mutate(agent)}>New key</Button>
                      <Button size="sm" variant="ghost" onClick={() => toggle.mutate(agent)}>{agent.is_active ? "Disable" : "Enable"}</Button>
                    </div>
                  )}
                </div>
                <div className="mt-4 overflow-x-auto">
                  {active.length === 0 ? <p className="text-sm text-slate-500">No active keys — this agent cannot call the API.</p> : (
                    <table className="w-full text-sm">
                      <thead className="table-head"><tr><th className="px-3 py-2">Key</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Created</th><th className="px-3 py-2">Last used</th><th className="px-3 py-2" /></tr></thead>
                      <tbody className="divide-y divide-slate-100">
                        {active.map((k) => (
                          <tr key={k.id}>
                            <td className="px-3 py-2 font-mono text-xs">pt_{k.prefix}_••••••••</td>
                            <td className="px-3 py-2">{k.name}</td>
                            <td className="px-3 py-2 text-xs text-slate-500">{formatTime(k.created_at)}</td>
                            <td className="px-3 py-2 text-xs text-slate-500">{k.last_used_at ? timeAgo(k.last_used_at) : "never"}</td>
                            <td className="px-3 py-2 text-right">
                              {can("admin") && <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirmRevoke({ agent, key: k })}>Revoke</Button>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {creating && <CreateAgent onClose={() => setCreating(false)} onCreated={(a) => { refresh(); setCreating(false); setSecret({ title: `${a.name} created`, value: a.webhook_secret, note: "This is the agent's callback signing secret (verify the X-PayTrust-Signature header with it). It is shown once. Next, create an API key and a policy for this agent." }); }} />}
      <Modal open={!!secret} title={secret?.title ?? ""} onClose={() => setSecret(null)}>
        {secret && <SecretBox value={secret.value} note={secret.note} />}
      </Modal>
      <Modal open={!!confirmRevoke} title="Revoke API key?" onClose={() => setConfirmRevoke(null)}>
        <p className="text-sm text-slate-600">Requests using <span className="font-mono">pt_{confirmRevoke?.key.prefix}_…</span> will be rejected immediately. This cannot be undone.</p>
        <ErrorNote error={revoke.error} />
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmRevoke(null)}>Cancel</Button>
          <Button variant="danger" loading={revoke.isPending} onClick={() => confirmRevoke && revoke.mutate(confirmRevoke)}>Revoke key</Button>
        </div>
      </Modal>
    </>
  );
}

function SecretBox({ value, note }: { value: string; note: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <code className="flex-1 break-all font-mono text-xs text-slate-900">{value}</code>
        <Button size="sm" variant="secondary" icon={<Copy className="size-3.5" />} onClick={() => navigator.clipboard.writeText(value).then(() => setCopied(true))}>{copied ? "Copied" : "Copy"}</Button>
      </div>
      <p className="text-sm text-slate-600">{note}</p>
    </div>
  );
}

function CreateAgent({ onClose, onCreated }: { onClose: () => void; onCreated: (a: Agent & { webhook_secret: string }) => void }) {
  const [form, setForm] = useState({ name: "", description: "", callback_url: "" });
  const create = useMutation({
    mutationFn: () => api<Agent & { webhook_secret: string }>("/v1/agents", { method: "POST", body: { name: form.name, description: form.description || null, callback_url: form.callback_url || null } }),
    onSuccess: onCreated,
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <Modal open title="New agent" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={120} autoFocus /></Field>
        <Field label="Description"><input className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label="Callback URL" hint="Optional. PayTrust POSTs here when a pending payment is approved, rejected or expires.">
          <input className="input" type="url" placeholder="https://agent.example.com/paytrust" value={form.callback_url} onChange={(e) => setForm({ ...form, callback_url: e.target.value })} />
        </Field>
        <ErrorNote error={create.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create agent</Button>
        </div>
      </form>
    </Modal>
  );
}
