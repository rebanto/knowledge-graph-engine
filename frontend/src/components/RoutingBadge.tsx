import { GitBranch, Search, Layers, Sparkles } from "lucide-react";
import type { RetrievalType } from "../types";
import { Badge } from "./ui";

const CONFIG: Record<RetrievalType, {
  label: string;
  icon: typeof GitBranch;
  tone: "graph" | "vector" | "hybrid" | "brass";
}> = {
  graph: { label: "Traced the graph", icon: GitBranch, tone: "graph" },
  vector: { label: "Read the sources", icon: Search, tone: "vector" },
  hybrid: { label: "Graph + sources", icon: Layers, tone: "hybrid" },
  deep_research: { label: "Deep Research", icon: Sparkles, tone: "brass" },
};

export function RoutingBadge({ type }: { type: RetrievalType }) {
  const { label, icon: Icon, tone } = CONFIG[type];
  return (
    <Badge tone={tone}>
      <Icon size={12} strokeWidth={2.25} />
      {label}
    </Badge>
  );
}
