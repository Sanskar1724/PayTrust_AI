import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Spinner, Stat, Tabs } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatNumber, formatTime, timeAgo } from "../lib/format";
import type { Job, JobStatus, JobSummary, Page } from "../lib/types";

const PAGE_SIZE = 50;
const KIND_LABEL: Record<string, string> = {
  "order.create": "Create payment order",
  "ai.investigate": "AI explanation",
  "callback.notify": "Agent callback",
};
const STATUS_STYLE: Record<JobStatus, string> = {
  PENDING: "bg-amber-50 text-amber-800 ring-amber-600/20",
  RUNNING: "bg-sky-50 text-sky-800 ring-sky-600/20",
  DONE: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  DEAD: "bg-red-50 text-red-800 ring-red-600/20",
};
type Filter = JobStatus | "ALL";

export function Jobs() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Filter>("DEAD");
  const [offset, setOffset] = useState(0);
  const params = { status: status === "ALL" ? undefined : status, limit: PAGE_SIZE, offset };
  const jobs = useQuery({ queryKey: ["jobs", params], queryFn: () => api<Page<Job>>(`/v1/jobs${query(params)}`), placeholderData: keepPreviousData, refetchInterval: 10_000 });
  const summary = useQuery({ queryKey: ["jobs", "summary"], queryFn: () => api<JobSummary>("/v1/jobs/summary"), refetchInterval: 10_000 });
  const retry = useMutation({
    mutationFn: (id: number) => api<Job>(`/v1/jobs/${id}/retry`, { method: "POST" }),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
  const counts = summary.data?.by_status;

  return (
    <>
      <PageHeader
        title="Background jobs"
        description="Work that follows a decision: creating the payment order, writing the AI explanation, calling the agent back. Each job is saved with the decision, retried with backoff if it fails, and lands here as dead if it keeps failing."
      />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Dead (need attention)" value={formatNumber(counts?.DEAD)} tone={counts?.DEAD ? "bad" : "good"} />
        <Stat label="Waiting or retrying" value={formatNumber(counts?.PENDING)} hint={summary.data?.oldest_pending_at ? `oldest ${timeAgo(summary.data.oldest_pending_at)}` : undefined} tone={counts?.PENDING ? "warn" : undefined} />
        <Stat label="Running now" value={formatNumber(counts?.RUNNING)} />
        <Stat label="Completed" value={formatNumber(counts?.DONE)} />
      </div>
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-5 py-3">
          <Tabs<Filter>
            value={status}
            onChange={(v) => { setStatus(v); setOffset(0); }}
            options={[
              { value: "DEAD", label: "Dead" }, { value: "PENDING", label: "Waiting" }, { value: "RUNNING", label: "Running" },
              { value: "DONE", label: "Done" }, { value: "ALL", label: "All" },
            ]}
          />
          {retry.error && <div className="w-full"><ErrorNote error={retry.error} /></div>}
        </div>
        {jobs.isLoading ? <Spinner /> : jobs.error ? <div className="p-5"><ErrorNote error={jobs.error} /></div> : !jobs.data?.items.length ? (
          <Empty title={status === "DEAD" ? "No dead jobs" : "No jobs"}>
            {status === "DEAD" ? "Every order, explanation and callback eventually succeeded." : undefined}
          </Empty>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="table-head">
                  <tr>
                    <th className="px-5 py-2.5">Job</th><th className="px-3 py-2.5">Payment</th><th className="px-3 py-2.5">Status</th>
                    <th className="px-3 py-2.5">Attempts</th><th className="px-3 py-2.5">When</th><th className="px-3 py-2.5">Last error</th><th className="px-5 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {jobs.data.items.map((j) => (
                    <tr key={j.id} className="align-top">
                      <td className="px-5 py-2.5">
                        <div className="font-medium text-slate-800">{KIND_LABEL[j.kind] ?? j.kind}</div>
                        <div className="font-mono text-[11px] text-slate-400">#{j.id} · {j.kind}</div>
                      </td>
                      <td className="px-3 py-2.5">{j.request_id ? <Link className="font-mono text-xs text-brand-700 hover:underline" to={`/payments/${j.request_id}`}>{j.request_id}</Link> : "—"}</td>
                      <td className="px-3 py-2.5"><Badge className={STATUS_STYLE[j.status]}>{j.status.toLowerCase()}</Badge></td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-xs text-slate-600">{j.attempts} / {j.max_attempts}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-xs text-slate-500">
                        {j.status === "PENDING" ? <>next try {formatTime(j.run_after)}</> : j.finished_at ? <>finished {timeAgo(j.finished_at)}</> : <>started {timeAgo(j.updated_at)}</>}
                        <div className="text-slate-400">created {formatTime(j.created_at)}</div>
                      </td>
                      <td className="max-w-md px-3 py-2.5 font-mono text-[11px] text-slate-500">{j.last_error ?? "—"}</td>
                      <td className="px-5 py-2.5 text-right">
                        {j.status === "DEAD" && can("admin") && (
                          <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" />}
                            loading={retry.isPending && retry.variables === j.id} onClick={() => retry.mutate(j.id)}>Retry</Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
              <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, jobs.data.total)} of {jobs.data.total}</span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
                <Button size="sm" variant="secondary" disabled={offset + PAGE_SIZE >= jobs.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
