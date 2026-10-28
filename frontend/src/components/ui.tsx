import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import { useEffect, type ButtonHTMLAttributes, type ReactNode } from "react";
import { ApiError } from "../lib/api";
import { humanize } from "../lib/format";
import type { Decision, PaymentStatus } from "../lib/types";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
  secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 shadow-sm",
  ghost: "text-slate-600 hover:bg-slate-100",
  danger: "bg-rose-600 text-white hover:bg-rose-700 shadow-sm",
  success: "bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm",
};

export function Button({
  variant = "primary",
  size = "md",
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm",
        VARIANTS[variant],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ title, action, children, className, padded = true }: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={clsx("card", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {action}
        </header>
      )}
      <div className={clsx(padded && "p-5")}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const DECISION_STYLE: Record<Decision, string> = {
  ALLOW: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  ASK_USER: "bg-amber-50 text-amber-800 ring-amber-600/25",
  DENY: "bg-rose-50 text-rose-700 ring-rose-600/20",
};

const STATUS_STYLE: Record<PaymentStatus, string> = {
  ALLOWED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  PENDING_APPROVAL: "bg-amber-50 text-amber-800 ring-amber-600/25",
  DENIED: "bg-rose-50 text-rose-700 ring-rose-600/20",
  REJECTED: "bg-rose-50 text-rose-700 ring-rose-600/20",
  EXPIRED: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", className ?? "bg-slate-100 text-slate-700 ring-slate-500/20")}>
      {children}
    </span>
  );
}

export const DecisionBadge = ({ decision }: { decision: Decision }) => (
  <Badge className={DECISION_STYLE[decision]}>{decision === "ASK_USER" ? "ASK USER" : decision}</Badge>
);

export const StatusBadge = ({ status }: { status: PaymentStatus }) => (
  <Badge className={STATUS_STYLE[status]}>{status === "PENDING_APPROVAL" ? "Pending approval" : humanize(status.toLowerCase())}</Badge>
);

export function RiskMeter({ score, compact }: { score: number; compact?: boolean }) {
  const color = score > 80 ? "bg-rose-600" : score > 60 ? "bg-orange-500" : score > 30 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <div className="flex items-center gap-2">
      <div className={clsx("overflow-hidden rounded-full bg-slate-200", compact ? "h-1.5 w-12" : "h-2 w-24")}>
        <div className={clsx("h-full rounded-full", color)} style={{ width: `${Math.max(3, score)}%` }} />
      </div>
      <span className="tabular-nums text-xs font-medium text-slate-700">{score}</span>
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className="card px-5 py-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={clsx("mt-1.5 text-2xl font-semibold tabular-nums tracking-tight",
        tone === "good" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : tone === "bad" ? "text-rose-700" : "text-slate-900")}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin" /> {label}…
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="text-sm font-medium text-slate-900">{title}</div>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.detail : error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {message}
      {error instanceof ApiError && error.requestId && (
        <span className="ml-1 font-mono text-[11px] text-rose-500">(ref {error.requestId.slice(0, 12)})</span>
      )}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Modal({ open, title, onClose, children, wide }: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-[10vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div className={clsx("card w-full", wide ? "max-w-2xl" : "max-w-md")} onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          <button className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose} aria-label="Close">
            <X className="size-4" />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={clsx("rounded-md px-3 py-1.5 text-xs font-medium transition",
            value === o.value ? "bg-slate-900 text-white" : "text-slate-600 hover:text-slate-900")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
