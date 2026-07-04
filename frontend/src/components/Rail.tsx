import { MessagesSquare, Network, Database, History, SquarePen, Plug } from "lucide-react";
import type { Workspace } from "../types";

export type Tab = "ask" | "explore" | "sources" | "connect";

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
  { id: "connect", label: "Connect", icon: Plug },
];

interface RailItemProps {
  label: string;
  icon: typeof Network;
  active?: boolean;
  badge?: number;
  onClick: () => void;
}

// A rail item carries its label inline (always visible) so the navigation
// is self-explanatory — no hover-to-discover guessing.
function RailItem({ label, icon: Icon, active, badge, onClick }: RailItemProps) {
  return (
    <button
      onClick={onClick}
      className="group relative flex h-14 w-[60px] flex-col items-center justify-center gap-1 rounded-xl transition-colors duration-200 ease-spring"
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
        className={`absolute -left-[10px] top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-full bg-brass transition-all duration-200 ease-spring ${
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
      <span
        className={`relative text-[10px] font-medium leading-none transition-colors duration-200 ${
          active ? "text-brass" : "text-muted group-hover:text-paper-dim"
        }`}
      >
        {label}
      </span>
      {badge ? (
        <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brass px-1 font-mono text-[9px] font-semibold text-ink-950">
          {badge > 99 ? "99" : badge}
        </span>
      ) : null}
    </button>
  );
}

interface RailProps {
  tab: Tab;
  onTab: (tab: Tab) => void;
  onNewThread: () => void;
  historyOpen: boolean;
  onToggleHistory: () => void;
  historyCount: number;
  workspace: Workspace | null;
}

export function Rail({
  tab,
  onTab,
  onNewThread,
  historyOpen,
  onToggleHistory,
  historyCount,
  workspace,
}: RailProps) {
  const initials = (workspace?.name ?? "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <aside className="relative z-30 flex h-full w-[76px] flex-shrink-0 flex-col items-center border-r border-ink-700/70 bg-ink-950/40 py-4 backdrop-blur-sm">
      <div className="mb-4 flex h-10 w-10 items-center justify-center" title="Lattice">
        <LatticeMark />
      </div>

      {/* Always-available "new question" — the universal escape hatch back to a
          fresh ask, no matter how deep in a thread or which page you're on. */}
      <button
        onClick={onNewThread}
        className="group mb-3 flex h-14 w-[60px] flex-col items-center justify-center gap-1 rounded-xl border border-brass/30 bg-brass-dim text-brass transition-colors duration-200 ease-spring hover:border-brass/50 hover:bg-brass/15 hover:glow-brass-soft"
        title="Start a new question"
      >
        <SquarePen size={18} strokeWidth={2} />
        <span className="text-[10px] font-medium leading-none">New</span>
      </button>

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
        label="History"
        icon={History}
        active={historyOpen}
        badge={historyCount}
        onClick={onToggleHistory}
      />

      {/* Workspace switcher — opens the drawer where the active workspace can be
          changed. Distinct from the page nav above so it reads as "where am I"
          rather than "which page". */}
      <div className="mt-auto">
        <button
          onClick={onToggleHistory}
          title={workspace ? `Workspace: ${workspace.name} — ${workspace.domain}` : "Pick a workspace"}
          className="group relative flex flex-col items-center gap-1.5"
        >
          <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-ink-700 bg-gradient-to-b from-ink-750 to-ink-800 font-display text-[13px] font-medium text-brass transition-colors group-hover:border-brass/35">
            {initials || "·"}
          </span>
          <span className="max-w-[68px] truncate text-[10px] text-faint transition-colors group-hover:text-paper-dim">
            {workspace?.name ?? "Workspace"}
          </span>
        </button>
      </div>
    </aside>
  );
}
