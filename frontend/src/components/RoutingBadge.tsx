import { GitBranch, Search, Layers } from "lucide-react";
import type { RetrievalType } from "../types";

const CONFIG: Record<RetrievalType, { label: string; icon: typeof GitBranch; className: string }> = {
  graph: {
    label: "Graph",
    icon: GitBranch,
    className: "text-graph bg-graph-dim border-graph/30",
  },
  vector: {
    label: "Documents",
    icon: Search,
    className: "text-vector bg-vector-dim border-vector/30",
  },
  hybrid: {
    label: "Graph + Documents",
    icon: Layers,
    className: "text-hybrid bg-hybrid-dim border-hybrid/30",
  },
};

export function RoutingBadge({ type }: { type: RetrievalType }) {
  const { label, icon: Icon, className } = CONFIG[type];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${className}`}
    >
      <Icon size={13} strokeWidth={2.25} />
      {label}
    </span>
  );
}
