import { useCallback, useEffect, useRef, useState } from "react";
import {
  Rss, Globe, FileText, BookOpen, Plus, Trash2,
  RefreshCw, Upload, CheckCircle, AlertCircle, Clock, Loader2,
} from "lucide-react";
import type { Source, SourceType } from "../types";
import { listSources, createSource, deleteSource, uploadPdf } from "../api";

const TYPE_META: Record<SourceType, {
  label: string;
  Icon: React.FC<{ size?: number; className?: string }>;
  placeholder: string;
  hint: string;
}> = {
  arxiv_feed: {
    label: "ArXiv",
    Icon: BookOpen,
    placeholder: "cs.AI",
    hint: "ArXiv category slug, e.g. cs.AI · cs.LG · cs.CL · stat.ML",
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
  Icon: React.FC<{ size?: number; className?: string }>;
}> = {
  pending:  { label: "Queued",     color: "text-zinc-400",    bg: "bg-zinc-800/60",      Icon: Clock },
  running:  { label: "Processing", color: "text-amber-400",   bg: "bg-amber-500/10",     Icon: Loader2 },
  success:  { label: "Ready",      color: "text-emerald-400", bg: "bg-emerald-500/10",   Icon: CheckCircle },
  error:    { label: "Error",      color: "text-rose-400",    bg: "bg-rose-500/10",      Icon: AlertCircle },
};

export function SourceManager({ workspaceId }: { workspaceId: string }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [type, setType] = useState<SourceType>("arxiv_feed");
  const [url, setUrl] = useState("");
  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    listSources(workspaceId).then(setSources).finally(() => setLoading(false));
  }, [workspaceId]);

  useEffect(() => {
    setLoading(true);
    setSources([]);
    refresh();
  }, [workspaceId, refresh]);

  // Poll while any source is pending/running
  useEffect(() => {
    const hasPending = sources.some((s) => s.status === "pending" || s.status === "running");
    if (hasPending && !pollRef.current) {
      pollRef.current = setInterval(refresh, 4000);
    } else if (!hasPending && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [sources, refresh]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setAdding(true);
    setFormError(null);
    try {
      const src = await createSource(workspaceId, type, url.trim());
      setSources((prev) => [src, ...prev]);
      setUrl("");
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
    } catch {
      setFormError("Upload failed. Make sure the file is a valid PDF.");
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(source: Source) {
    await deleteSource(workspaceId, source.id);
    setSources((prev) => prev.filter((s) => s.id !== source.id));
  }

  const activeMeta = TYPE_META[type];
  const runningCount = sources.filter((s) => s.status === "running" || s.status === "pending").length;

  return (
    <div className="flex h-full flex-col overflow-y-auto px-8 py-8 scrollbar-thin">
      <div className="mx-auto w-full max-w-2xl">

        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-[18px] font-semibold text-zinc-100">Sources</h2>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              {loading
                ? "Loading…"
                : sources.length === 0
                ? "No sources yet — add one below to start building the knowledge graph."
                : `${sources.length} source${sources.length !== 1 ? "s" : ""}${runningCount ? ` · ${runningCount} processing…` : ""}`}
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

        {/* Add-source form */}
        <div className="mb-6 rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
          <p className="mb-3 text-[13px] font-medium text-zinc-400">Add a source</p>

          {/* Type selector */}
          <div className="mb-3 flex flex-wrap gap-2">
            {(Object.keys(TYPE_META) as SourceType[]).map((t) => {
              const { label, Icon } = TYPE_META[t];
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => { setType(t); setUrl(""); setFormError(null); }}
                  className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
                    type === t
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

          <p className="mb-2.5 text-[11px] text-zinc-600">{activeMeta.hint}</p>

          {type === "pdf_upload" ? (
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
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={activeMeta.placeholder}
                className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-[13px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-600"
              />
              <button
                type="submit"
                disabled={adding || !url.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-zinc-100 px-3 py-2 text-[13px] font-medium text-zinc-900 transition-colors hover:bg-white disabled:opacity-40"
              >
                {adding ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                Add
              </button>
            </form>
          )}

          {formError && <p className="mt-2 text-[12px] text-rose-400">{formError}</p>}
        </div>

        {/* Source list */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={16} className="animate-spin text-zinc-600" />
          </div>
        ) : sources.length === 0 ? (
          <div className="rounded-xl border border-zinc-800/40 bg-zinc-900/20 p-10 text-center">
            <p className="text-[13px] text-zinc-500">No sources yet.</p>
            <p className="mt-1 text-[12px] text-zinc-600">
              Add an ArXiv category, RSS feed, web URL, or upload a PDF to begin.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {sources.map((src) => {
              const sm = STATUS_META[src.status] ?? STATUS_META.error;
              const tm = TYPE_META[src.type as SourceType];
              const TypeIcon = tm?.Icon ?? Globe;
              const typeLabel = tm?.label ?? src.type;
              const { Icon: StatusIcon, label: statusLabel, color: statusColor, bg: statusBg } = sm;

              return (
                <div
                  key={src.id}
                  className="flex items-start gap-3 rounded-xl border border-zinc-800/60 bg-zinc-900/20 p-3.5"
                >
                  <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-zinc-800/60">
                    <TypeIcon size={14} className="text-zinc-400" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[11.5px] font-medium text-zinc-500">{typeLabel}</span>
                      <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] font-medium ${statusBg} ${statusColor}`}>
                        <StatusIcon
                          size={9}
                          className={src.status === "running" ? "animate-spin" : ""}
                        />
                        {statusLabel}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate font-mono text-[12px] text-zinc-300">
                      {src.type === "pdf_upload"
                        ? src.url.replace(/^.*[\\/]/, "").replace(/^[0-9a-f-]{36}_/, "")
                        : src.url}
                    </p>
                    {src.last_error && (
                      <p className="mt-1 text-[11px] text-rose-400/80">{src.last_error}</p>
                    )}
                    {src.last_fetched && (
                      <p className="mt-0.5 text-[10.5px] text-zinc-600">
                        Last fetched {new Date(src.last_fetched).toLocaleString()}
                      </p>
                    )}
                  </div>

                  <button
                    onClick={() => handleDelete(src)}
                    title="Remove source"
                    className="mt-0.5 flex-shrink-0 rounded-md p-1.5 text-zinc-600 transition-colors hover:bg-zinc-800 hover:text-rose-400"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
