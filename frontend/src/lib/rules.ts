// Plain-language descriptions of policy rules, shared by the policy cards, the history view
// and payment evidence.
import { formatINR, humanize } from "./format";
import { WEEKDAYS, type Merchant } from "./types";

type Rules = Record<string, unknown>;

const DAY_LABEL: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

/** "Mon–Sat", "Mon, Wed, Fri" or "every day". */
export function describeDays(days: string[] | null | undefined): string {
  if (!days?.length || days.length === 7) return "every day";
  const idx = days.map((d) => WEEKDAYS.indexOf(d as (typeof WEEKDAYS)[number])).filter((i) => i >= 0).sort((a, b) => a - b);
  const contiguous = idx.every((v, i) => i === 0 || v === idx[i - 1] + 1);
  if (contiguous && idx.length > 2) return `${DAY_LABEL[WEEKDAYS[idx[0]]]}–${DAY_LABEL[WEEKDAYS[idx[idx.length - 1]]]}`;
  return idx.map((i) => DAY_LABEL[WEEKDAYS[i]]).join(", ");
}

/** "06:00–22:00 · Mon–Sat", or null when the policy has no time window. */
export function describeWindow(r: { allowed_from?: unknown; allowed_until?: unknown; allowed_days?: unknown }): string | null {
  const hours = r.allowed_from && r.allowed_until ? `${r.allowed_from}–${r.allowed_until}` : null;
  const days = (r.allowed_days as string[] | null)?.length ? describeDays(r.allowed_days as string[]) : null;
  if (!hours && !days) return null;
  return [hours, days].filter(Boolean).join(" · ");
}

/** Merchant-limit keys are a merchant id or registered name; show the name. */
export function merchantLabel(key: string, merchants: Merchant[] = []): string {
  const byId = /^\d+$/.test(key) ? merchants.find((m) => String(m.id) === key) : undefined;
  if (byId) return byId.name;
  return merchants.find((m) => m.name.toLowerCase() === key.toLowerCase())?.name ?? key;
}

const FIELD_LABEL: Record<string, string> = {
  daily_limit: "Daily limit", weekly_limit: "Weekly limit", monthly_limit: "Monthly limit",
  max_transaction: "Max per payment", approval_threshold: "Ask user above",
  allowed_categories: "Allowed categories", blocked_categories: "Blocked categories",
  allowed_merchants: "Allowed merchants", blocked_merchants: "Blocked merchants",
  category_limits: "Category limits", merchant_limits: "Merchant limits",
  allowed_from: "Allowed from", allowed_until: "Allowed until", allowed_days: "Allowed days", is_active: "Active",
};
const MONEY = new Set(["daily_limit", "weekly_limit", "monthly_limit", "max_transaction", "approval_threshold"]);

function show(key: string, value: unknown, merchants: Merchant[]): string {
  if (value === null || value === undefined || (Array.isArray(value) && !value.length)) return "not set";
  if (MONEY.has(key)) return formatINR(value as number);
  if (key === "is_active") return value ? "yes" : "no (paused)";
  if (key === "allowed_days") return describeDays(value as string[]);
  if (Array.isArray(value)) return value.map((v) => humanize(String(v))).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, number>)
      .map(([k, v]) => `${key === "merchant_limits" ? merchantLabel(k, merchants) : humanize(k)} ${formatINR(v)}`).join(", ");
  }
  return String(value);
}

/** What changed between two versions' rules, as "Daily limit: ₹1,00,000 → ₹90,000". */
export function diffRules(before: Rules | null, after: Rules, merchants: Merchant[] = []): string[] {
  if (!before) return ["Policy created"];
  return Object.keys(FIELD_LABEL)
    .filter((k) => JSON.stringify(before[k] ?? null) !== JSON.stringify(after[k] ?? null))
    .map((k) => `${FIELD_LABEL[k]}: ${show(k, before[k], merchants)} → ${show(k, after[k], merchants)}`);
}

/** Empty input → null (not set); otherwise a whole number. */
export const optionalAmount = (raw: string): number | null => (raw.trim() === "" ? null : Math.max(0, Math.round(Number(raw))));
