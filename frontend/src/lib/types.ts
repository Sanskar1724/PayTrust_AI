export type Decision = "ALLOW" | "ASK_USER" | "DENY";
export type PaymentStatus = "ALLOWED" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED" | "EXPIRED" | "DENIED";
export type Role = "admin" | "reviewer" | "viewer";

export interface Operator {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface RiskFactor {
  name: string;
  severity: "low" | "medium" | "high" | "critical";
  score: number;
  details: string;
}

export interface Counterfactual {
  action: Decision;
  fraud_exposure: number;
  false_positive_cost: number;
  operational_cost: number;
  customer_friction: string;
  expected_total_cost: number;
  allowed_by_policy: boolean;
  rationale: string;
}

export interface AiResult {
  explanation: string;
  summary: string;
  concerns: string[];
  review_questions: string[];
  confidence: number;
  provider: string;
  model: string;
  latency_ms: number;
  fallback_used: boolean;
  errors: string[];
}

export interface PaymentSummary {
  request_id: string;
  status: PaymentStatus;
  decision: Decision;
  risk_score: number;
  risk_level: string;
  user_id: number;
  agent_id: number;
  merchant_name: string;
  amount: number;
  category: string;
  source: string;
  expires_at: string | null;
  created_at: string;
}

export interface Payment extends PaymentSummary {
  reasons: string[];
  requires_approval: boolean;
  merchant_id: number;
  currency: string;
  description: string | null;
  agent_reason: string | null;
  policy_result: {
    authorized: boolean;
    requires_approval: boolean;
    violations: string[];
    reasons: string[];
    daily_spent: number;
    policy: { daily_limit: number; max_transaction: number; approval_threshold: number } | null;
  };
  risk_result: {
    risk_score: number;
    risk_level: string;
    factors: RiskFactor[];
    context?: Record<string, number | boolean>;
  };
  simulation: { counterfactuals: Counterfactual[]; recommended: Decision; reason: string; disclaimer: string };
  ai: AiResult | null;
  order: { id?: string; status?: string; mode?: string; error?: string } | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  processing_ms: number;
  updated_at: string;
  duplicate: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Stats {
  total: number;
  decisions: Record<Decision, number>;
  pending_approvals: number;
  amount_approved: number;
  amount_blocked: number;
  latency_ms: { p50: number; p95: number; p99: number };
  top_violations: [string, number][];
  top_factors: [string, number][];
  series: { hour: string; ALLOW: number; ASK_USER: number; DENY: number }[];
}

export interface User {
  id: number;
  name: string;
  email: string | null;
  external_ref: string | null;
  created_at: string;
}

export interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface Agent {
  id: number;
  name: string;
  description: string | null;
  callback_url: string | null;
  is_active: boolean;
  created_at: string;
  keys: ApiKey[];
}

export interface Merchant {
  id: number;
  name: string;
  category: string | null;
  risk_tier: "standard" | "high";
  created_at: string;
}

export interface Policy {
  id: number;
  user_id: number;
  agent_id: number;
  daily_limit: number;
  max_transaction: number;
  approval_threshold: number;
  allowed_categories: string[];
  blocked_categories: string[];
  allowed_merchants: string[] | null;
  blocked_merchants: string[] | null;
  is_active: boolean;
  updated_at: string;
  updated_by: string | null;
}

export interface AuditEvent {
  id: number;
  created_at: string;
  actor: string;
  event_type: string;
  request_id: string | null;
  data: Record<string, unknown>;
}

export interface ArenaStats {
  planned: number;
  completed: number;
  errors: number;
  correct: number;
  accuracy: number;
  malicious: { total: number; caught: number; missed: number };
  legit: { total: number; blocked: number; asked: number; allowed: number };
  decisions: Record<string, number>;
  personas: Record<string, { title: string; intent: string; expectation: string; requests: number; correct: number; decisions: Record<string, number> }>;
  latency_ms: { client_p50: number; client_p95: number; client_p99: number; server_p50: number; server_p95: number };
  elapsed_seconds: number;
  throughput_rps: number;
  mistakes: { persona: string; request_id: string; decision: string | null; status_code: number; expected: string[] }[];
}

export interface ArenaRun {
  id: string;
  scenario: string;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  params: { requests: number; concurrency: number };
  stats: Partial<ArenaStats>;
  error: string | null;
  started_by: string;
  started_at: string;
  finished_at: string | null;
}

export interface ThresholdPoint {
  threshold: number;
  precision: number;
  recall: number;
  f1: number;
  false_positive_rate: number;
  tp: number;
  fp: number;
  tn: number;
  fn: number;
  fraud_exposure: number;
  false_positive_cost: number;
  operational_cost: number;
  expected_total_cost: number;
}

export const CATEGORIES = [
  "electronics", "books", "travel", "food", "fashion", "grocery", "fuel", "gambling", "financial_products",
] as const;
