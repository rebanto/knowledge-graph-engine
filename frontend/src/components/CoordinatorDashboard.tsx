import { useCallback, useEffect, useRef, useState } from "react";
import {
  Server, Cpu, Loader2, RefreshCw, Activity,
  Clock, RotateCcw, Skull, Wifi,
} from "lucide-react";
import type { CoordinatorStatus, CoordinatorWorker } from "../types";
import { getCoordinatorStatus } from "../api";

const STATE_META: Record<string, { label: string; color: string; bg: string; border: string }> = {
  processing: { label: "Working", color: "text-brass", bg: "bg-brass-dim", border: "border-brass/20" },
  idle: { label: "Idle", color: "text-ok", bg: "bg-ok-dim", border: "border-ok/20" },
  dead: { label: "Gone", color: "text-flag", bg: "bg-flag-dim", border: "border-flag/20" },
};

function StatTile({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-800/40 px-4 py-3">
      <p className={`font-display text-[26px] font-medium tabular-nums leading-none ${accent ?? "text-paper"}`}>{value}</p>
      <p className="mt-1.5 text-[11.5px] text-muted">{label}</p>
    </div>
  );
}

function WorkerCard({ w, timeout }: { w: CoordinatorWorker; timeout: number }) {
  const sm = STATE_META[w.state] ?? STATE_META.idle;
  const pct = w.total > 0 ? Math.round((w.completed / w.total) * 100) : 0;
  // A heartbeat older than 60% of the timeout is drifting toward a reap.
  const stale = w.state === "processing" && timeout > 0 && w.seconds_since_heartbeat > timeout * 0.6;
  // Only processing workers heartbeat; for idle/dead it's just last contact, so
  // don't frame a large idle gap as a worrying "since heartbeat".
  const contactLabel = w.state === "processing" ? "since heartbeat" : "since last seen";

  return (
    <div className={`rounded-xl border bg-ink-800/40 p-3.5 ${sm.border}`}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-ink-750">
          <Cpu size={14} className={sm.color} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-mono text-[12.5px] text-paper">{w.worker_id}</span>
            <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] font-medium ${sm.bg} ${sm.color}`}>
              {w.state === "processing" && <Loader2 size={9} className="animate-spin" />}
              {w.state === "dead" && <Skull size={9} />}
              {sm.label}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted">
            <span className="inline-flex items-center gap-1">
              <Server size={10} /> {w.host || "—"}
            </span>
            <span className={`inline-flex items-center gap-1 ${stale ? "text-brass/90" : ""}`}>
              <Clock size={10} /> {w.seconds_since_heartbeat.toFixed(1)}s {contactLabel}
            </span>
          </div>

          {w.state === "processing" && w.total > 0 && (
            <div className="mt-2">
              <div className="mb-1 flex items-center justify-between text-[10.5px] text-muted">
                <span className="font-mono text-muted">batch {w.batch_id?.slice(0, 8) ?? "—"}</span>
                <span>{w.completed}/{w.total} docs · {pct}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
                <div className="h-full rounded-full bg-brass transition-all" style={{ width: `${pct}%` }} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function CoordinatorDashboard() {
  const [status, setStatus] = useState<CoordinatorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getCoordinatorStatus());
    } catch {
      setStatus({ available: false });
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll continuously while the pool is live so progress/heartbeats stay fresh.
  useEffect(() => {
    refresh();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, [refresh]);

  useEffect(() => {
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null; }
    const delay = status?.available ? 3000 : 8000;
    pollRef.current = setTimeout(refresh, delay);
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, [status, refresh]);

  const workers = status?.workers ?? [];
  const timeout = status?.heartbeat_timeout_secs ?? 30;

  return (
    <div className="flex h-full flex-col overflow-y-auto px-8 py-8 scrollbar-thin">
      <div className="mx-auto w-full max-w-2xl">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-[18px] font-semibold text-zinc-100">
              <Server size={16} className="text-zinc-400" />
              Worker pool
            </h2>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              Distributed ingestion coordinator — live worker health and batch progress.
            </p>
          </div>
          <button
            onClick={refresh}
            title="Refresh"
            className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={16} className="animate-spin text-zinc-600" />
          </div>
        ) : !status?.available ? (
          <div className="rounded-xl border border-zinc-800/40 bg-zinc-900/20 p-10 text-center">
            <Activity size={20} className="mx-auto mb-3 text-zinc-700" />
            <p className="text-[13px] text-zinc-400">Distributed worker pool not enabled</p>
            <p className="mx-auto mt-1.5 max-w-md text-[12px] leading-relaxed text-zinc-600">
              The default local setup ingests with a single RQ worker. To run the
              coordinator + gRPC worker pool, start it with{" "}
              <code className="rounded bg-zinc-900 px-1 py-0.5 font-mono text-[11px] text-zinc-400">
                docker compose --profile distributed up -d --scale dworker=3
              </code>
              .
            </p>
          </div>
        ) : (
          <>
            <div className="mb-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <StatTile
                label={`Live workers${status.worker_count ? ` of ${status.worker_count}` : ""}`}
                value={status.live_worker_count ?? 0}
                accent="text-emerald-400"
              />
              <StatTile label="Pending docs" value={status.pending ?? 0}
                accent={(status.pending ?? 0) > 0 ? "text-amber-400" : undefined} />
              <StatTile label="Reassignments" value={status.reassignments ?? 0} />
              <StatTile label="Dead workers" value={status.dead_workers ?? 0}
                accent={(status.dead_workers ?? 0) > 0 ? "text-rose-400" : undefined} />
            </div>

            <div className="mb-3 flex items-center gap-2 text-[11.5px] text-zinc-500">
              <Wifi size={12} className="text-emerald-400" />
              Connected · heartbeat timeout {timeout}s
            </div>

            {workers.length === 0 ? (
              <div className="rounded-xl border border-zinc-800/40 bg-zinc-900/20 p-8 text-center">
                <p className="text-[13px] text-zinc-500">
                  Coordinator is up, but no workers have registered yet.
                </p>
                <p className="mt-1 text-[12px] text-zinc-600">
                  Scale workers with{" "}
                  <code className="rounded bg-zinc-900 px-1 py-0.5 font-mono text-[11px] text-zinc-400">
                    --scale dworker=3
                  </code>
                  .
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {workers.map((w) => (
                  <WorkerCard key={w.worker_id} w={w} timeout={timeout} />
                ))}
              </div>
            )}

            {(status.reassignments ?? 0) > 0 && (
              <p className="mt-4 flex items-center gap-1.5 text-[11.5px] text-zinc-600">
                <RotateCcw size={11} />
                {status.reassignments} document(s) were requeued after a worker stopped
                heartbeating — idempotent writes make the reprocessing harmless.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
