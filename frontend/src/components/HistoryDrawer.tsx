import { useState } from "react";
import { Plus, Trash2, Loader2, X } from "lucide-react";
import type { ReportSummary, Workspace } from "../types";
import { relativeTime } from "../lib/time";
import { WorkspaceSelector } from "./WorkspaceSelector";

const DOT: Record<string, string> = {
  graph: "bg-graph",
  vector: "bg-vector",
  hybrid: "bg-hybrid",
};

interface HistoryDrawerProps {
  open: boolean;
  onClose: () => void;
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

export function HistoryDrawer({
  open,
  onClose,
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
}: HistoryDrawerProps) {
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

  if (!open) return null;

  return (
    <aside className="animate-drawer-in relative z-20 flex h-full w-72 flex-shrink-0 flex-col border-r border-ink-700/70 bg-ink-900/70 backdrop-blur-md">
      <div className="flex items-center justify-between px-4 pt-5 pb-3">
        <div className="leading-none">
          <p className="font-display text-[17px] font-medium tracking-tight text-paper">Lattice</p>
          <p className="mt-1 font-display text-[11px] italic text-faint">a research instrument</p>
        </div>
        <button
          onClick={onClose}
          title="Collapse"
          className="rounded-md p-1.5 text-faint transition-colors hover:bg-ink-800 hover:text-paper-dim"
        >
          <X size={15} />
        </button>
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
          className="flex w-full items-center gap-2 rounded-lg border border-brass/30 bg-brass-dim px-3 py-2 text-sm font-medium text-brass transition-colors hover:border-brass/50 hover:bg-brass/15 hover:glow-brass-soft"
        >
          <Plus size={15} />
          Ask something new
        </button>
      </div>

      <div className="mt-5 flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        <p className="eyebrow px-2 pb-2 text-faint">Asked before</p>
        <div className="flex flex-col gap-0.5">
          {reports.map((r) => (
            <div
              key={r.id}
              className={`group relative flex flex-col gap-1 rounded-md px-2.5 py-2 transition-colors ${
                activeId === r.id ? "bg-ink-750" : "hover:bg-ink-800"
              }`}
            >
              <button onClick={() => onSelect(r)} className="flex w-full flex-col gap-1 text-left">
                <div className="flex items-center gap-1.5 pr-5">
                  <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${DOT[r.retrieval_type]}`} />
                  <p
                    className={`truncate text-[13px] leading-tight ${
                      activeId === r.id ? "text-paper" : "text-paper-dim group-hover:text-paper"
                    }`}
                  >
                    {r.question}
                  </p>
                </div>
                <p className="pl-3 text-[11px] text-faint">{relativeTime(r.created_at)}</p>
              </button>

              <button
                onClick={(e) => handleDelete(r.id, e)}
                disabled={deletingId === r.id}
                title="Forget this question"
                className="absolute right-1.5 top-1.5 hidden rounded p-1 text-faint transition-colors hover:bg-ink-650 hover:text-flag group-hover:flex disabled:opacity-40"
              >
                {deletingId === r.id ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
              </button>
            </div>
          ))}
          {reports.length === 0 && (
            <p className="px-2 py-3 font-display text-[12.5px] italic text-faint">Nothing asked yet.</p>
          )}
        </div>
      </div>
    </aside>
  );
}
