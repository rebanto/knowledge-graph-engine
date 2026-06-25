import { useCallback, useEffect, useRef, useState } from "react";
import {
  Rss, Globe, FileText, BookOpen, Plus, Trash2,
  RefreshCw, Upload, CheckCircle, AlertCircle, Clock,
  Loader2, ChevronDown, ChevronRight, RotateCcw,
  Wifi, WifiOff, Activity,
} from "lucide-react";
import type { Source, SourceType, SourceJobsResponse, QueueStatus } from "../types";
import {
  listSources, createSource, deleteSource, uploadPdf,
  getSourceJobs, retrySource, getQueueStatus, cleanupWorkspace,
} from "../api";

// ── Type / status metadata ─────────────────────────────────────────────────────

const TYPE_META: Record<SourceType, {
  label: string;
  Icon: React.FC<{ size?: number; className?: string }>;
  placeholder: string;
  hint: string;
}> = {
  arxiv_feed: {
    label: "ArXiv",
    Icon: BookOpen,
    placeholder: "cs.AI, cs.LG · 2401.12345 · graph neural networks",
    hint: "Category (cs.AI, stat.ML), paper ID or arxiv.org link, or search keywords. Comma-separate multiple categories.",
  },
  rss: {
    label: "RSS",
    Icon: Rss,
    placeholder: "https://example.com/feed.xml",
    hint: "Full URL of any RSS or Atom feed",
  },
  web_url: {
    label: "Web URL",
    Icon: Globe,
    placeholder: "https://example.com/article",
    hint: "Any web page — the text will be scraped and ingested",
  },
  pdf_upload: {
    label: "PDF",
    Icon: FileText,
    placeholder: "",
    hint: "Upload a PDF directly — up to ~50 MB",
  },
};

const STATUS_META: Record<string, {
  label: string;
  color: string;
  bg: string;
  border: string;
  Icon: React.FC<{ size?: number; className?: string }>;
}> = {
  pending: {
    label: "Waiting",
    color: "text-muted",
    bg: "bg-ink-700",
    border: "border-ink-600",
    Icon: Clock,
  },
  running: {
    label: "Reading",
    color: "text-brass",
    bg: "bg-brass-dim",
    border: "border-brass/20",
    Icon: Loader2,
  },
  success: {
    label: "Ready",
    color: "text-ok",
    bg: "bg-ok-dim",
    border: "border-ok/20",
    Icon: CheckCircle,
  },
  error: {
    label: "Failed",
    color: "text-flag",
    bg: "bg-flag-dim",
    border: "border-flag/20",
    Icon: AlertCircle,
  },
};

type FilterTab = "all" | "active" | "ready" | "error";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtDuration(created: string, completed: string | null): string {
  if (!completed) return "";
  const ms = new Date(completed).getTime() - new Date(created).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtRelative(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function shortenUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname.slice(0, 45);
    return u.hostname + path + (u.pathname.length > 45 ? "…" : "");
  } catch {
    return url.slice(0, 60) + (url.length > 60 ? "…" : "");
  }
}

function totalQueued(qs: QueueStatus): number {
  return Object.values(qs.queues).reduce((acc, q) => acc + q.queued + q.started, 0);
}

// ── Worker status banner ───────────────────────────────────────────────────────

function WorkerBanner({ status }: { status: QueueStatus | null }) {
  if (!status) return null;

  const queued = totalQueued(status);
  const online = status.worker_count > 0;

  if (online && queued === 0) return null;

  if (!online) {
    return (
      <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-500/25 bg-amber-500/8 px-4 py-3">
        <WifiOff size={14} className="mt-0.5 flex-shrink-0 text-amber-400" />
        <div className="min-w-0">
          <p className="text-[12.5px] font-medium text-amber-300">
            Ingestion worker is offline
            {queued > 0 && ` — ${queued} job${queued !== 1 ? "s" : ""} queued`}
          </p>
          <p className="mt-0.5 text-[11.5px] text-amber-400/70">
            Sources stay at "Queued" until the worker starts.{" "}
            Run{" "}
            <code className="rounded bg-zinc-900 px-1 py-0.5 text-[11px] text-zinc-300">
              .\dev.ps1
            </code>{" "}
            to start all services.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-5 flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/6 px-4 py-2.5">
      <Wifi size={13} className="flex-shrink-0 text-emerald-400" />
      <p className="text-[12px] text-emerald-300/80">
        <span className="font-medium text-emerald-300">
          {status.worker_count} worker{status.worker_count !== 1 ? "s" : ""} online
        </span>
        {queued > 0 && ` · ${queued} job${queued !== 1 ? "s" : ""} in queue`}
      </p>
    </div>
  );
}

// ── Job row (inside expanded card) ────────────────────────────────────────────

function JobRow({ job }: { job: SourceJobsResponse["jobs"][number] }) {
  const running = job.status === "running";
  const failed = job.status === "failed";

  return (
    <div className={`flex items-start gap-2.5 rounded-lg px-3 py-1.5 ${failed ? "bg-rose-500/5" : ""}`}>
      {running ? (
        <Loader2 size={11} className="mt-0.5 flex-shrink-0 animate-spin text-amber-400" />
      ) : failed ? (
        <AlertCircle size={11} className="mt-0.5 flex-shrink-0 text-rose-400" />
      ) : (
        <CheckCircle size={11} className="mt-0.5 flex-shrink-0 text-emerald-400/70" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[11px] text-zinc-400">
          {job.document_url ? shortenUrl(job.document_url) : "—"}
        </p>
        {failed && job.error && (
          <p className="mt-0.5 line-clamp-1 text-[10.5px] text-rose-400/80">{job.error}</p>
        )}
      </div>
      <span className="flex-shrink-0 text-[10.5px] text-zinc-600">
        {fmtDuration(job.created_at, job.completed_at)}
      </span>
    </div>
  );
}

// ── Source card ────────────────────────────────────────────────────────────────

interface SourceCardProps {
  src: Source;
  jobData: SourceJobsResponse | null;
  loadingJobs: boolean;
  expanded: boolean;
  retrying: boolean;
  deleting: boolean;
  onToggleExpand: () => void;
  onRetry: () => void;
  onDelete: () => void;
}

function SourceCard({
  src, jobData, loadingJobs, expanded, retrying, deleting,
  onToggleExpand, onRetry, onDelete,
}: SourceCardProps) {
  const sm = STATUS_META[src.status] ?? STATUS_META.error;
  const tm = TYPE_META[src.type as SourceType];
  const TypeIcon = tm?.Icon ?? Globe;
  const { Icon: StatusIcon, label: statusLabel, color: statusColor, bg: statusBg, border: statusBorder } = sm;

  const displayUrl =
    src.type === "pdf_upload"
      ? src.url.replace(/^.*[\\/]/, "").replace(/^[0-9a-f-]{36}_/, "")
      : src.url;

  const canRetry = src.status !== "running";

  return (
    <div className={`rounded-xl border bg-zinc-900/20 transition-all ${statusBorder}`}>
      {/* Card header */}
      <div className="flex items-start gap-3 p-3.5">
        <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-zinc-800/60">
          <TypeIcon size={14} className="text-zinc-400" />
        </div>

        <div className="min-w-0 flex-1">
          {/* Type label + status badge */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11.5px] font-medium text-zinc-500">
              {tm?.label ?? src.type}
            </span>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] font-medium ${statusBg} ${statusColor}`}
            >
              <StatusIcon size={9} className={src.status === "running" ? "animate-spin" : ""} />
              {statusLabel}
            </span>
          </div>

          {/* URL */}
          <p
            className="mt-0.5 truncate font-mono text-[12px] text-zinc-300"
            title={displayUrl}
          >
            {displayUrl}
          </p>

          {/* Stats + timestamps */}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
            {jobData && (
              <span className="text-[10.5px] text-zinc-500">
                <span className="text-emerald-400/80">{jobData.success} docs</span>
                {jobData.failed > 0 && (
                  <>
                    {" · "}
                    <span className="text-rose-400/80">{jobData.failed} failed</span>
                  </>
                )}
                {jobData.running > 0 && (
                  <>
                    {" · "}
                    <span className="text-amber-400/80">{jobData.running} running</span>
                  </>
                )}
              </span>
            )}
            {src.last_fetched ? (
              <span className="text-[10.5px] text-zinc-600">
                Fetched {fmtRelative(src.last_fetched)}
              </span>
            ) : (
              <span className="text-[10.5px] text-zinc-600">
                Added {fmtRelative(src.created_at)}
              </span>
            )}
            {src.error_count > 0 && (
              <span className="text-[10.5px] text-rose-500/60">
                {src.error_count} error{src.error_count !== 1 ? "s" : ""}
              </span>
            )}
          </div>

          {/* Last error */}
          {src.last_error && (
            <p className="mt-1 line-clamp-2 text-[11px] text-rose-400/80">{src.last_error}</p>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex flex-shrink-0 items-center gap-0.5">
          {canRetry && (
            <button
              onClick={onRetry}
              disabled={retrying}
              title="Re-ingest this source"
              className="flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300 disabled:opacity-40"
            >
              {retrying
                ? <Loader2 size={11} className="animate-spin" />
                : <RotateCcw size={11} />}
              <span>Re-ingest</span>
            </button>
          )}
          <button
            onClick={onDelete}
            disabled={deleting}
            title="Remove source"
            className="rounded-md p-1.5 text-zinc-600 transition-colors hover:bg-zinc-800 hover:text-rose-400 disabled:opacity-40"
          >
            {deleting
              ? <Loader2 size={13} className="animate-spin" />
              : <Trash2 size={13} />}
          </button>
        </div>
      </div>

      {/* Expand toggle */}
      <button
        onClick={onToggleExpand}
        className="flex w-full items-center gap-1.5 border-t border-zinc-800/40 px-3.5 py-2 text-left text-[11px] text-zinc-600 transition-colors hover:bg-zinc-800/20 hover:text-zinc-400"
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {loadingJobs ? (
          <span className="flex items-center gap-1.5">
            <Loader2 size={10} className="animate-spin" />
            Loading jobs…
          </span>
        ) : jobData ? (
          expanded
            ? `Hide job history`
            : `Show job history — ${jobData.total} jobs · ${jobData.success} ok · ${jobData.failed} failed`
        ) : (
          "Show job history"
        )}
      </button>

      {/* Job list (expanded) */}
      {expanded && (
        <div className="border-t border-zinc-800/40 px-1 py-2">
          {!jobData || loadingJobs ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 size={14} className="animate-spin text-zinc-600" />
            </div>
          ) : jobData.jobs.length === 0 ? (
            <p className="px-3 py-2 text-[11px] text-zinc-600">No jobs recorded yet.</p>
          ) : (
            <div className="flex flex-col gap-0.5">
              {jobData.jobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
              {jobData.total > jobData.jobs.length && (
                <p className="px-3 pt-1 text-[10.5px] text-zinc-600">
                  Showing latest {jobData.jobs.length} of {jobData.total} jobs
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function SourceManager({ workspaceId }: { workspaceId: string }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [loading, setLoading] = useState(true);

  // Expandable job history per source
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Record<string, SourceJobsResponse>>({});
  const [loadingJobs, setLoadingJobs] = useState<Record<string, boolean>>({});

  // Per-source action states
  const [retrying, setRetrying] = useState<Record<string, boolean>>({});
  const [deleting, setDeleting] = useState<Record<string, boolean>>({});


  // Add-source form
  const [addOpen, setAddOpen] = useState(false);
  const [addType, setAddType] = useState<SourceType>("arxiv_feed");
  const [addUrl, setAddUrl] = useState("");
  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Polling
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollIntervalRef = useRef(3000);
  const unchangedCountRef = useRef(0);
  const prevStatusKeyRef = useRef("");

  // ── Fetching ─────────────────────────────────────────────────────────────────

  const refresh = useCallback(async () => {
    const [srcs, qs] = await Promise.allSettled([
      listSources(workspaceId),
      getQueueStatus(),
    ]);
    if (srcs.status === "fulfilled") setSources(srcs.value);
    if (qs.status === "fulfilled") setQueueStatus(qs.value);
    setLoading(false);
  }, [workspaceId]);

  // Silently purge stale graph/vector data left behind by deleted sources.
  // Runs on workspace load, after delete, and when the user hits Refresh.
  const syncQuietly = useCallback(async () => {
    try { await cleanupWorkspace(workspaceId); } catch { /* ignore */ }
  }, [workspaceId]);

  useEffect(() => {
    setLoading(true);
    setSources([]);
    setJobs({});
    setExpandedId(null);
    setFilter("all");
    pollIntervalRef.current = 3000;
    unchangedCountRef.current = 0;
    prevStatusKeyRef.current = "";
    refresh();
    syncQuietly();
  }, [workspaceId, refresh, syncQuietly]);

  // Exponential-backoff poll while any source is active
  useEffect(() => {
    const hasPending = sources.some((s) => s.status === "pending" || s.status === "running");
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null; }
    if (!hasPending) { pollIntervalRef.current = 3000; unchangedCountRef.current = 0; return; }

    const statusKey = sources.map((s) => `${s.id}:${s.status}`).join("|");
    if (statusKey === prevStatusKeyRef.current) {
      unchangedCountRef.current += 1;
    } else {
      unchangedCountRef.current = 0;
      prevStatusKeyRef.current = statusKey;
    }

    const delay = unchangedCountRef.current > 10 ? 30_000 : pollIntervalRef.current;
    pollIntervalRef.current = Math.min(pollIntervalRef.current * 1.5, 15_000);

    pollRef.current = setTimeout(refresh, delay);
    return () => { if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null; } };
  }, [sources, refresh]);

  // Re-fetch job data when expanded source finishes
  useEffect(() => {
    if (!expandedId) return;
    const src = sources.find((s) => s.id === expandedId);
    if (src && (src.status === "success" || src.status === "error")) {
      loadJobsFor(expandedId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources]);

  // ── Actions ──────────────────────────────────────────────────────────────────

  async function loadJobsFor(sourceId: string) {
    if (loadingJobs[sourceId]) return;
    setLoadingJobs((p) => ({ ...p, [sourceId]: true }));
    try {
      const data = await getSourceJobs(workspaceId, sourceId);
      setJobs((p) => ({ ...p, [sourceId]: data }));
    } finally {
      setLoadingJobs((p) => ({ ...p, [sourceId]: false }));
    }
  }

  function handleToggleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
    } else {
      setExpandedId(id);
      if (!jobs[id]) loadJobsFor(id);
    }
  }

  async function handleRetry(sourceId: string) {
    setRetrying((p) => ({ ...p, [sourceId]: true }));
    try {
      const { source } = await retrySource(workspaceId, sourceId);
      setSources((prev) => prev.map((s) => (s.id === sourceId ? source : s)));
    } finally {
      setRetrying((p) => ({ ...p, [sourceId]: false }));
    }
  }

  async function handleDelete(sourceId: string) {
    setDeleting((p) => ({ ...p, [sourceId]: true }));
    try {
      await deleteSource(workspaceId, sourceId);
      setSources((prev) => prev.filter((s) => s.id !== sourceId));
      if (expandedId === sourceId) setExpandedId(null);
      syncQuietly(); // purge any residual graph/vector data in the background
    } finally {
      setDeleting((p) => ({ ...p, [sourceId]: false }));
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!addUrl.trim()) return;
    setAdding(true);
    setFormError(null);
    try {
      const src = await createSource(workspaceId, addType, addUrl.trim());
      setSources((prev) => [src, ...prev]);
      setAddUrl("");
      setAddOpen(false);
    } catch {
      setFormError("Failed to add source. Check the value and try again.");
    } finally {
      setAdding(false);
    }
  }

  async function handleUpload(file: File) {
    setAdding(true);
    setFormError(null);
    try {
      const src = await uploadPdf(workspaceId, file);
      setSources((prev) => [src, ...prev]);
      if (fileRef.current) fileRef.current.value = "";
      setAddOpen(false);
    } catch {
      setFormError("Upload failed. Make sure the file is a valid PDF.");
    } finally {
      setAdding(false);
    }
  }

  // ── Filter counts ─────────────────────────────────────────────────────────────

  const counts = {
    all: sources.length,
    active: sources.filter((s) => s.status === "pending" || s.status === "running").length,
    ready: sources.filter((s) => s.status === "success").length,
    error: sources.filter((s) => s.status === "error").length,
  };

  const filtered = sources.filter((s) => {
    if (filter === "active") return s.status === "pending" || s.status === "running";
    if (filter === "ready") return s.status === "success";
    if (filter === "error") return s.status === "error";
    return true;
  });

  const FILTER_TABS: { id: FilterTab; label: string }[] = [
    { id: "all",    label: `All (${counts.all})` },
    { id: "active", label: `Active (${counts.active})` },
    { id: "ready",  label: `Ready (${counts.ready})` },
    { id: "error",  label: `Error (${counts.error})` },
  ];

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col overflow-y-auto px-8 py-8 scrollbar-thin">
      <div className="mx-auto w-full max-w-2xl">

        {/* Worker / queue status banner */}
        <WorkerBanner status={queueStatus} />

        {/* Page header */}
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-[18px] font-semibold text-zinc-100">Sources</h2>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              {loading
                ? "Loading…"
                : sources.length === 0
                ? "No sources yet — add one to start building the knowledge graph."
                : [
                    `${sources.length} source${sources.length !== 1 ? "s" : ""}`,
                    counts.active > 0 && `${counts.active} processing`,
                    counts.error > 0 && `${counts.error} error${counts.error !== 1 ? "s" : ""}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
            </p>
          </div>
          <button
            onClick={() => { refresh(); syncQuietly(); }}
            title="Refresh"
            className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {/* Add source — collapsed trigger or expanded form */}
        {!addOpen ? (
          <button
            onClick={() => setAddOpen(true)}
            className="mb-5 flex w-full items-center gap-2 rounded-xl border border-dashed border-zinc-800 px-4 py-3 text-[13px] text-zinc-500 transition-colors hover:border-zinc-600 hover:text-zinc-300"
          >
            <Plus size={14} />
            Add a source…
          </button>
        ) : (
          <div className="mb-5 rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-[13px] font-medium text-zinc-300">Add a source</p>
              <button
                onClick={() => { setAddOpen(false); setAddUrl(""); setFormError(null); }}
                className="text-[11px] text-zinc-600 hover:text-zinc-400"
              >
                Cancel
              </button>
            </div>

            {/* Source type tabs */}
            <div className="mb-3 flex flex-wrap gap-2">
              {(Object.keys(TYPE_META) as SourceType[]).map((t) => {
                const { label, Icon } = TYPE_META[t];
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => { setAddType(t); setAddUrl(""); setFormError(null); }}
                    className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
                      addType === t
                        ? "border-zinc-600 bg-zinc-800 text-zinc-100"
                        : "border-zinc-800 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300"
                    }`}
                  >
                    <Icon size={11} />
                    {label}
                  </button>
                );
              })}
            </div>

            <p className="mb-2.5 text-[11px] text-zinc-600">{TYPE_META[addType].hint}</p>

            {addType === "pdf_upload" ? (
              <div>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={(e) => { if (e.target.files?.[0]) handleUpload(e.target.files[0]); }}
                />
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  disabled={adding}
                  className="flex items-center gap-2 rounded-lg border border-dashed border-zinc-700 px-4 py-3 text-[13px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-300 disabled:opacity-50"
                >
                  {adding ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                  {adding ? "Uploading…" : "Choose a PDF file…"}
                </button>
              </div>
            ) : (
              <form onSubmit={handleAdd} className="flex gap-2">
                <input
                  value={addUrl}
                  onChange={(e) => {
                    const val = e.target.value;
                    setAddUrl(val);
                    // Auto-switch to Web URL when a non-arxiv https:// address is
                    // typed into the ArXiv field — prevents the silent wrong-type bug
                    // where a Wikipedia URL gets submitted as an arxiv_feed and finds 0 docs.
                    if (
                      addType === "arxiv_feed" &&
                      /^https?:\/\//i.test(val) &&
                      !/arxiv\.org/i.test(val)
                    ) {
                      setAddType("web_url");
                    }
                    setFormError(null);
                  }}
                  placeholder={TYPE_META[addType].placeholder}
                  className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-[13px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-600"
                />
                <button
                  type="submit"
                  disabled={adding || !addUrl.trim()}
                  className="flex items-center gap-1.5 rounded-lg bg-zinc-100 px-3 py-2 text-[13px] font-medium text-zinc-900 transition-colors hover:bg-white disabled:opacity-40"
                >
                  {adding ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                  Add
                </button>
              </form>
            )}

            {formError && <p className="mt-2 text-[12px] text-rose-400">{formError}</p>}
          </div>
        )}

        {/* Filter tabs */}
        {sources.length > 0 && (
          <div className="mb-4 flex gap-1">
            {FILTER_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setFilter(tab.id)}
                className={`rounded-lg px-3 py-1.5 text-[11.5px] font-medium transition-colors ${
                  filter === tab.id
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Source list */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={16} className="animate-spin text-zinc-600" />
          </div>
        ) : sources.length === 0 ? (
          <div className="rounded-xl border border-zinc-800/40 bg-zinc-900/20 p-10 text-center">
            <Activity size={20} className="mx-auto mb-3 text-zinc-700" />
            <p className="text-[13px] text-zinc-500">No sources yet.</p>
            <p className="mt-1 text-[12px] text-zinc-600">
              Add an ArXiv category, RSS feed, web URL, or upload a PDF to begin.
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-zinc-800/40 bg-zinc-900/20 p-8 text-center">
            <p className="text-[13px] text-zinc-500">No sources match this filter.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {filtered.map((src) => (
              <SourceCard
                key={src.id}
                src={src}
                jobData={jobs[src.id] ?? null}
                loadingJobs={!!loadingJobs[src.id]}
                expanded={expandedId === src.id}
                retrying={!!retrying[src.id]}
                deleting={!!deleting[src.id]}
                onToggleExpand={() => handleToggleExpand(src.id)}
                onRetry={() => handleRetry(src.id)}
                onDelete={() => handleDelete(src.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
