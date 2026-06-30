type Tone = "neutral" | "brass" | "graph" | "vector" | "hybrid" | "ok" | "flag";
type Size = "sm" | "md";

const TONE: Record<Tone, string> = {
  neutral: "border-ink-700 bg-ink-800/70 text-faint",
  brass: "border-brass/30 bg-brass-dim text-brass",
  graph: "border-graph/30 bg-graph-dim text-graph",
  vector: "border-vector/30 bg-vector-dim text-vector",
  hybrid: "border-hybrid/30 bg-hybrid-dim text-hybrid",
  ok: "border-ok/25 bg-ok-dim text-ok",
  flag: "border-flag/30 bg-flag/10 text-flag",
};

const SIZE: Record<Size, string> = {
  sm: "gap-1 px-2 py-0.5 text-[10.5px]",
  md: "gap-1.5 px-2.5 py-1 text-[11px]",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  size?: Size;
}

// The one pill shape — routing labels, trust scores, status tags, counts.
export function Badge({ tone = "neutral", size = "md", className = "", children, ...rest }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium ${SIZE[size]} ${TONE[tone]} ${className}`}
      {...rest}
    >
      {children}
    </span>
  );
}
