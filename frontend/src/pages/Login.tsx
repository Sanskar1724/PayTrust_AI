import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Button, ErrorNote, Field } from "../components/ui";
import { useAuth } from "../lib/auth";

export function Login() {
  const { operator, login } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (operator) return <Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-ink p-12 text-slate-300 lg:flex">
        <div className="flex items-center gap-3">
          <img src="/logo.svg" alt="" className="size-9" />
          <span className="text-lg font-semibold text-white">PayTrust AI</span>
        </div>
        <div className="max-w-md">
          <h1 className="text-3xl font-semibold leading-tight text-white">Every payment an AI agent makes, checked before money moves.</h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-400">
            Deterministic policy and risk engines decide ALLOW, ASK USER or DENY in milliseconds, with the
            evidence for every decision. AI explains — it never approves.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-3 text-center text-xs">
            {[["ALLOW", "text-emerald-400"], ["ASK USER", "text-amber-300"], ["DENY", "text-rose-400"]].map(([d, c]) => (
              <div key={d} className="rounded-lg border border-white/10 bg-white/5 py-3">
                <div className={`font-semibold ${c}`}>{d}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="text-xs text-slate-500">Policy → Risk → Decision → Evidence</div>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Sign in</h2>
            <p className="mt-1 text-sm text-slate-500">Operator console for reviewers and admins.</p>
          </div>
          <Field label="Email">
            <input className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </Field>
          <Field label="Password">
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <ErrorNote error={error} />
          <Button type="submit" loading={busy} className="w-full">Sign in</Button>
          {import.meta.env.DEV && (
            <p className="text-center text-xs text-slate-400">Local default: admin@paytrust.local / admin12345</p>
          )}
        </form>
      </div>
    </div>
  );
}
