import { Network, Plus } from "lucide-react";
import type { ReportSummary } from "../types";
import { relativeTime } from "../lib/time";

const DOT: Record<string, string> = {
  graph: "bg-graph",
  vector: "bg-vector",
  hybrid: "bg-hybrid",
};

interface SidebarProps {
  reports: ReportSummary[];
  activeId: string | null;
  onSelect: (report: ReportSummary) => void;
  onNew: () => void;
}

export function Sidebar({ reports, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col border-r border-zinc-800/60 bg-[#0c0c0e]">
      <div className="flex items-center gap-2 px-5 pt-6 pb-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-100/5 ring-1 ring-zinc-700/50">
          <Network size={15} className="text-zinc-300" strokeWidth={2} />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-tight text-zinc-100">Lattice</p>
          <p className="text-[11px] leading-none text-zinc-500">Knowledge graph engine</p>
        </div>
      </div>

      <div className="px-3">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-sm text-zinc-300 transition-colors hover:border-zinc-700 hover:bg-zinc-900 hover:text-zinc-100"
        >
          <Plus size={15} />
          New question
        </button>
      </div>

      <div className="mt-5 flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-600">
          Recent
        </p>
        <div className="flex flex-col gap-0.5">
          {reports.map((r) => (
            <button
              key={r.id}
              onClick={() => onSelect(r)}
              className={`group flex flex-col gap-1 rounded-md px-2.5 py-2 text-left transition-colors ${
                activeId === r.id ? "bg-zinc-800/70" : "hover:bg-zinc-900"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${DOT[r.retrieval_type]}`} />
                <p className="truncate text-[13px] leading-tight text-zinc-300 group-hover:text-zinc-100">
                  {r.question}
                </p>
              </div>
              <p className="pl-3 text-[11px] text-zinc-600">{relativeTime(r.created_at)}</p>
            </button>
          ))}
          {reports.length === 0 && (
            <p className="px-2 py-3 text-[12px] text-zinc-600">No questions asked yet.</p>
          )}
        </div>
      </div>
    </aside>
  );
}
