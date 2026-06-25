import { useState } from "react";
import { Plus, Trash2, Loader2 } from "lucide-react";
import type { ReportSummary, Workspace } from "../types";
import { relativeTime } from "../lib/time";
import { WorkspaceSelector } from "./WorkspaceSelector";

const DOT: Record<string, string> = {
  graph: "bg-graph",
  vector: "bg-vector",
  hybrid: "bg-hybrid",
};

// The wordmark: a tiny three-node lattice that echoes the favicon.
function LatticeMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <g stroke="#d6a44e" strokeOpacity="0.5" strokeWidth="1.3" strokeLinecap="round">
        <line x1="7" y1="8" x2="18" y2="6.5" />
        <line x1="7" y1="8" x2="7" y2="18" />
        <line x1="7" y1="8" x2="18.5" y2="18.5" />
        <line x1="7" y1="18" x2="18.5" y2="18.5" />
      </g>
      <circle cx="7" cy="8" r="2.6" fill="#100e0b" stroke="#d6a44e" strokeWidth="1.4" />
      <circle cx="18" cy="6.5" r="2" fill="#100e0b" stroke="#d6a44e" strokeWidth="1.4" />
      <circle cx="7" cy="18" r="2" fill="#100e0b" stroke="#d6a44e" strokeWidth="1.4" />
      <circle cx="18.5" cy="18.5" r="3" fill="#d6a44e" />
    </svg>
  );
}

interface SidebarProps {
  reports: ReportSummary[];
  activeId: string | null;
  onSelect: (report: ReportSummary) => void;
  onNew: () => void;
  onDeleteReport: (reportId: string) => Promise<void>;
  workspaces: Workspace[];
  workspaceId: string;
  onWorkspaceChange: (id: string) => void;
  onCreateWorkspace: (name: string, domain: string, description: string, autoDiscover: boolean) => Promise<void>;
  onUpdateWorkspace: (id: string, name: string, domain: string, description: string) => Promise<void>;
  onDeleteWorkspace: (id: string) => Promise<void>;
}

export function Sidebar({
  reports,
  activeId,
  onSelect,
  onNew,
  onDeleteReport,
  workspaces,
  workspaceId,
  onWorkspaceChange,
  onCreateWorkspace,
  onUpdateWorkspace,
  onDeleteWorkspace,
}: SidebarProps) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function handleDelete(reportId: string, e: React.MouseEvent) {
    e.stopPropagation();
    setDeletingId(reportId);
    try {
      await onDeleteReport(reportId);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col border-r border-ink-700 bg-ink-850">
      <div className="flex items-center gap-2.5 px-5 pt-6 pb-5">
        <LatticeMark />
        <div className="leading-none">
          <p className="font-display text-[19px] font-medium tracking-tight text-paper">Lattice</p>
          <p className="mt-1 font-display text-[11.5px] italic text-faint">a research instrument</p>
        </div>
      </div>

      <WorkspaceSelector
        workspaces={workspaces}
        activeId={workspaceId}
        onSelect={onWorkspaceChange}
        onCreate={onCreateWorkspace}
        onUpdate={onUpdateWorkspace}
        onDelete={onDeleteWorkspace}
      />

      <div className="px-3">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-brass/25 bg-brass-dim px-3 py-2 text-sm font-medium text-brass transition-colors hover:border-brass/45 hover:bg-brass/15"
        >
          <Plus size={15} />
          Ask something new
        </button>
      </div>

      <div className="mt-5 flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-600">
          History
        </p>
        <div className="flex flex-col gap-0.5">
          {reports.map((r) => (
            <div
              key={r.id}
              className={`group relative flex flex-col gap-1 rounded-md px-2.5 py-2 transition-colors ${
                activeId === r.id ? "bg-zinc-800/70" : "hover:bg-zinc-900"
              }`}
            >
              <button
                onClick={() => onSelect(r)}
                className="flex flex-col gap-1 text-left w-full"
              >
                <div className="flex items-center gap-1.5 pr-5">
                  <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${DOT[r.retrieval_type]}`} />
                  <p className="truncate text-[13px] leading-tight text-zinc-300 group-hover:text-zinc-100">
                    {r.question}
                  </p>
                </div>
                <p className="pl-3 text-[11px] text-zinc-600">{relativeTime(r.created_at)}</p>
              </button>

              <button
                onClick={(e) => handleDelete(r.id, e)}
                disabled={deletingId === r.id}
                title="Delete this query"
                className="absolute right-1.5 top-1.5 hidden rounded p-1 text-zinc-600 transition-colors hover:bg-zinc-700/60 hover:text-rose-400 group-hover:flex disabled:opacity-40"
              >
                {deletingId === r.id
                  ? <Loader2 size={11} className="animate-spin" />
                  : <Trash2 size={11} />
                }
              </button>
            </div>
          ))}
          {reports.length === 0 && (
            <p className="px-2 py-3 text-[12px] text-zinc-600">No history yet.</p>
          )}
        </div>
      </div>
    </aside>
  );
}
