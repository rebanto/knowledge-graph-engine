import { MessagesSquare, Network, Database, Server, History } from "lucide-react";
import type { Workspace } from "../types";

export type Tab = "ask" | "explore" | "sources" | "cluster";

// The wordmark: a tiny three-node lattice that echoes the favicon.
function LatticeMark() {
  return (
    <svg width="30" height="30" viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <g stroke="#d6a44e" strokeOpacity="0.5" strokeWidth="1.3" strokeLinecap="round">
        <line x1="7" y1="8" x2="18" y2="6.5" />
        <line x1="7" y1="8" x2="7" y2="18" />
        <line x1="7" y1="8" x2="18.5" y2="18.5" />
        <line x1="7" y1="18" x2="18.5" y2="18.5" />
      </g>
      <circle cx="7" cy="8" r="2.6" fill="#100e0b" stroke="#d6a44e" strokeWidth="1.4" />
      <circle cx="18" cy="6.5" r="2" fill="#100e0b" stroke="#d6a44e" strokeWidth="1.4" />
      <circle cx="7" cy="18" r="2" fill="#100e0b" stroke="#d6a44e" strokeWidth="1.4" />
      <circle cx="18.5" cy="18.5" r="3" fill="#d6a44e" className="animate-pulse-soft" />
    </svg>
  );
}

const NAV: { id: Tab; label: string; icon: typeof Network }[] = [
  { id: "ask", label: "Ask", icon: MessagesSquare },
  { id: "explore", label: "Graph", icon: Network },
  { id: "sources", label: "Sources", icon: Database },
  { id: "cluster", label: "Cluster", icon: Server },
];

interface RailItemProps {
  label: string;
  icon: typeof Network;
  active?: boolean;
  badge?: number;
  onClick: () => void;
}

function RailItem({ label, icon: Icon, active, badge, onClick }: RailItemProps) {
  return (
    <button
      onClick={onClick}
      className="group relative flex h-11 w-11 items-center justify-center rounded-xl transition-colors duration-200 ease-spring"
      aria-label={label}
      aria-current={active ? "page" : undefined}
    >
      {/* active backdrop + left signal bar */}
      <span
        className={`absolute inset-0 rounded-xl border transition-all duration-200 ease-spring ${
          active
            ? "border-brass/25 bg-brass-dim glow-brass-soft"
            : "border-transparent group-hover:border-ink-700 group-hover:bg-ink-800/60"
        }`}
      />
      <span
        className={`absolute -left-[10px] top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-brass transition-all duration-200 ease-spring ${
          active ? "opacity-100 glow-brass-soft" : "opacity-0"
        }`}
      />
      <Icon
        size={18}
        strokeWidth={active ? 2.25 : 2}
        className={`relative transition-colors duration-200 ${
          active ? "text-brass" : "text-muted group-hover:text-paper-dim"
        }`}
      />
      {badge ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brass px-1 font-mono text-[9px] font-semibold text-ink-950">
          {badge > 99 ? "99" : badge}
        </span>
      ) : null}

      {/* hover label */}
      <span className="pointer-events-none absolute left-full z-50 ml-3 hidden whitespace-nowrap rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-[11.5px] text-paper-dim shadow-xl shadow-black/50 group-hover:block">
        {label}
      </span>
    </button>
  );
}

interface RailProps {
  tab: Tab;
  onTab: (tab: Tab) => void;
  historyOpen: boolean;
  onToggleHistory: () => void;
  historyCount: number;
  workspace: Workspace | null;
}

export function Rail({ tab, onTab, historyOpen, onToggleHistory, historyCount, workspace }: RailProps) {
  const initials = (workspace?.name ?? "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <aside className="relative z-30 flex h-full w-[68px] flex-shrink-0 flex-col items-center border-r border-ink-700/70 bg-ink-950/40 py-4 backdrop-blur-sm">
      <div className="mb-5 flex h-10 w-10 items-center justify-center" title="Lattice">
        <LatticeMark />
      </div>

      <nav className="flex flex-col items-center gap-1.5">
        {NAV.map((n) => (
          <RailItem
            key={n.id}
            label={n.label}
            icon={n.icon}
            active={tab === n.id}
            onClick={() => onTab(n.id)}
          />
        ))}
      </nav>

      <div className="my-3 h-px w-7 bg-ink-700/80" />

      <RailItem
        label={historyOpen ? "Hide history" : "History"}
        icon={History}
        active={historyOpen}
        badge={historyCount}
        onClick={onToggleHistory}
      />

      <div className="mt-auto">
        <button
          onClick={onToggleHistory}
          title={workspace ? `${workspace.name} — ${workspace.domain}` : "Workspace"}
          className="group relative flex h-11 w-11 items-center justify-center rounded-xl border border-ink-700 bg-gradient-to-b from-ink-750 to-ink-800 font-display text-[13px] font-medium text-brass transition-colors hover:border-brass/35"
        >
          {initials || "·"}
          <span className="pointer-events-none absolute bottom-0 left-full z-50 ml-3 hidden max-w-[200px] truncate whitespace-nowrap rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-[11.5px] text-paper-dim shadow-xl shadow-black/50 group-hover:block">
            {workspace?.name ?? "Pick a workspace"}
          </span>
        </button>
      </div>
    </aside>
  );
}
