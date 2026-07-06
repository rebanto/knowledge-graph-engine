import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Eye, Info, Loader2, Network, Unlink, X } from "lucide-react";
import { fetchGaps, generateHypothesis } from "../api";
import type { Hypothesis, ResearchGap } from "../types";
import { Badge, Button, Card, SectionLabel } from "./ui";
import { BRASS, NODE_COLOR, NODE_FALLBACK, PAPER } from "../lib/palette";

function gapKey(gap: ResearchGap) {
  return `${gap.source.name}::${gap.target.name}`;
}

type GapStrength = {
  pct: number;
  tier: "strong" | "moderate" | "emerging";
  label: string;
};

export function strengthOf(gap: ResearchGap, maxScore: number): GapStrength {
  if (maxScore <= 0) return { pct: 0, tier: "emerging", label: "Emerging" };
  const pct = Math.max(0, Math.min(1, gap.score / maxScore));
  if (pct >= 0.66) return { pct, tier: "strong", label: "Strong" };
  if (pct >= 0.33) return { pct, tier: "moderate", label: "Moderate" };
  return { pct, tier: "emerging", label: "Emerging" };
}

export function plainSummary(gap: ResearchGap): string {
  const count = gap.common_neighbor_count;
  const noun = count === 1 ? "intermediary" : "intermediaries";
  const names = gap.shared_intermediaries
    .slice(0, 2)
    .map((ev) => ev.intermediary.name)
    .filter(Boolean);
  const nameList = names.length > 0 ? ` (${names.join(", ")}${count > 2 ? "..." : ""})` : "";
  const bridge = gap.interdisciplinary ? " Bridges two topic clusters." : "";
  const fallback = gap.why_notable ? ` ${gap.why_notable}` : "";
  return `Both connect to ${count} shared ${noun}${nameList} but have no direct link.${bridge}${count === 0 ? fallback : ""}`;
}

function strengthColor(tier: GapStrength["tier"]) {
  if (tier === "strong") return BRASS;
  if (tier === "moderate") return NODE_COLOR.Concept;
  return PAPER.muted;
}

function EntityPill({
  name,
  type,
  compact = false,
}: {
  name: string;
  type?: string | null;
  compact?: boolean;
}) {
  const color = type ? NODE_COLOR[type] ?? NODE_FALLBACK : NODE_FALLBACK;
  return (
    <span
      className={`inline-flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 font-medium ${
        compact ? "max-w-[110px] text-[11px]" : "text-[12px]"
      }`}
      style={{ borderColor: `${color}42`, backgroundColor: `${color}14`, color }}
      title={type ? `${name} (${type})` : name}
    >
      <span className="truncate">{name}</span>
      {type && <span className="font-mono text-[9.5px] opacity-60">{type}</span>}
    </span>
  );
}

function RelationList({ rels }: { rels: string[] }) {
  if (rels.length === 0) return <span className="text-faint">related</span>;
  return (
    <span className="flex min-w-0 flex-wrap justify-center gap-1">
      {rels.map((rel) => (
        <span
          key={rel}
          className="rounded px-1.5 py-0.5 font-mono text-[9.5px] leading-none"
          style={{ backgroundColor: `${BRASS}18`, color: BRASS }}
        >
          {rel}
        </span>
      ))}
    </span>
  );
}

function HypothesisBlock({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <div className="mt-3 rounded-lg border border-brass/25 bg-brass-dim p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <Badge tone="brass" size="sm">CONJECTURE</Badge>
        <span className="font-mono text-[10px] uppercase text-brass/75">
          {hypothesis.confidence} confidence
        </span>
      </div>
      <p className="text-[13px] font-medium leading-relaxed text-paper">
        {hypothesis.statement}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
        <span>Predicted edge</span>
        <span className="rounded px-1.5 py-0.5 font-mono text-[10px] text-brass">
          {hypothesis.predicted_relationship_type}
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-paper-dim">{hypothesis.reasoning}</p>
      <p className="mt-2 border-t border-brass/15 pt-2 text-[11.5px] leading-relaxed text-brass/75">
        {hypothesis.caveat}
      </p>
    </div>
  );
}

interface ResearchGapsProps {
  workspaceId: string;
  selectedGap: ResearchGap | null;
  onSelectGap: (gap: ResearchGap | null) => void;
  onHoverGap?: (gap: ResearchGap | null) => void;
}

export function ResearchGaps({ workspaceId, selectedGap, onSelectGap, onHoverGap }: ResearchGapsProps) {
  const [gaps, setGaps] = useState<ResearchGap[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAllEvidence, setShowAllEvidence] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<"strength" | "shared">("strength");
  const [bridgesOnly, setBridgesOnly] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hypotheses, setHypotheses] = useState<Record<string, Hypothesis>>({});
  const [generating, setGenerating] = useState<string | null>(null);
  const maxScore = gaps[0]?.score ?? 0;

  const displayedGaps = useMemo(() => {
    const filtered = bridgesOnly ? gaps.filter((gap) => gap.interdisciplinary) : gaps;
    return [...filtered].sort((a, b) => {
      if (sortBy === "shared") {
        return b.common_neighbor_count - a.common_neighbor_count || b.score - a.score;
      }
      return b.score - a.score || b.common_neighbor_count - a.common_neighbor_count;
    });
  }, [bridgesOnly, gaps, sortBy]);

  useEffect(() => {
    let alive = true;
    fetchGaps(workspaceId, 10)
      .then((result) => {
        if (!alive) return;
        setGaps(result);
      })
      .catch(() => {
        if (!alive) return;
        setError("Couldn't load research gaps.");
        setGaps([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [workspaceId]);

  async function handleGenerate(gap: ResearchGap) {
    const key = gapKey(gap);
    setGenerating(key);
    setError(null);
    try {
      const hypothesis = await generateHypothesis(workspaceId, gap.source.name, gap.target.name);
      setHypotheses((prev) => ({ ...prev, [key]: hypothesis }));
    } catch {
      setError("Couldn't generate a hypothesis for that gap.");
    } finally {
      setGenerating(null);
    }
  }

  function toggleEvidence(key: string) {
    setShowAllEvidence((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <aside className="flex h-full w-[380px] flex-shrink-0 flex-col border-r border-ink-700 bg-ink-900/45">
      <div className="border-b border-ink-700/70 px-4 py-3.5">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="relative flex items-center gap-1.5">
              <SectionLabel>Research Gaps</SectionLabel>
              <button
                type="button"
                onClick={() => setInfoOpen((open) => !open)}
                className="rounded-full p-1 text-faint transition-colors hover:bg-ink-750 hover:text-paper-dim"
                aria-label="Explain research gaps"
              >
                <Info size={13} />
              </button>
              {infoOpen && (
                <Card
                  variant="flat"
                  className="absolute left-0 top-7 z-20 w-[310px] p-3 shadow-2xl shadow-black/30"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-[12px] font-semibold text-paper-dim">How to read this</p>
                    <button
                      type="button"
                      onClick={() => setInfoOpen(false)}
                      className="rounded p-1 text-faint hover:bg-ink-750 hover:text-paper-dim"
                      aria-label="Close explainer"
                    >
                      <X size={12} />
                    </button>
                  </div>
                  <ul className="space-y-1.5 text-[11.5px] leading-relaxed text-muted">
                    <li>A gap is a pair with shared intermediaries but no direct link yet.</li>
                    <li>Strength is relative to this list, using the top score as 100%.</li>
                    <li>A bridge connects two different topic clusters.</li>
                  </ul>
                </Card>
              )}
            </div>
            <p className="mt-1 text-[11.5px] text-faint">
              Entity pairs that are one link away from connecting.
            </p>
          </div>
          <Badge tone="neutral" size="sm">{gaps.length}</Badge>
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-faint">Sort:</span>
            <div className="inline-flex rounded-lg border border-ink-700 bg-ink-850/70 p-0.5">
              {(["strength", "shared"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setSortBy(mode)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    sortBy === mode ? "bg-ink-700 text-paper-dim" : "text-faint hover:text-paper-dim"
                  }`}
                >
                  {mode === "strength" ? "Strength" : "Shared"}
                </button>
              ))}
            </div>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-[11.5px] text-faint">
            <input
              type="checkbox"
              checked={bridgesOnly}
              onChange={(event) => setBridgesOnly(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-ink-700 bg-ink-850 accent-brass"
            />
            Bridges only
          </label>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3 scrollbar-thin">
        {loading && (
          <div className="flex items-center gap-2 px-2 py-3 text-[12px] text-muted">
            <Loader2 size={14} className="animate-spin text-brass" />
            Scanning for missing links...
          </div>
        )}

        {error && <p className="px-2 py-2 text-[12px] text-flag">{error}</p>}

        {!loading && gaps.length === 0 && !error && (
          <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
            <Network size={20} className="text-ghost" />
            <p className="text-[13px] font-medium text-paper-dim">No structural gaps found</p>
            <p className="text-[12px] leading-relaxed text-faint">
              More connected sources will give the link predictor more evidence.
            </p>
          </div>
        )}

        {!loading && gaps.length > 0 && displayedGaps.length === 0 && !error && (
          <div className="px-2 py-6 text-center text-[12px] text-faint">
            No bridge gaps in this set.
          </div>
        )}

        <div className="flex flex-col gap-2">
          {displayedGaps.map((gap, index) => {
            const key = gapKey(gap);
            const isExpanded = expanded === key;
            const isSelected = selectedGap && gapKey(selectedGap) === key;
            const hypothesis = hypotheses[key];
            const strength = strengthOf(gap, maxScore);
            const color = strengthColor(strength.tier);
            const evidenceOpen = showAllEvidence.has(key);
            const evidence = evidenceOpen
              ? gap.shared_intermediaries
              : gap.shared_intermediaries.slice(0, 3);
            const hiddenEvidence = gap.shared_intermediaries.length - evidence.length;
            return (
              <Card
                key={key}
                variant="flat"
                className={`overflow-hidden transition-colors ${
                  isSelected ? "border-brass/35 bg-brass-dim" : ""
                }`}
                onMouseEnter={() => onHoverGap?.(gap)}
                onMouseLeave={() => onHoverGap?.(null)}
              >
                <button
                  onClick={() => {
                    setExpanded(isExpanded ? null : key);
                    onSelectGap(isSelected ? null : gap);
                  }}
                  className="flex w-full items-start gap-2 p-3 text-left hover:bg-ink-750/45"
                >
                  <span className="mt-1 text-faint">
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                      <span className="font-mono text-[11px] text-faint">#{index + 1}</span>
                      <EntityPill name={gap.source.name} type={gap.source.type} />
                      <span
                        className="inline-flex items-center gap-1 rounded-full border border-flag/20 bg-flag/10 px-1.5 py-0.5 text-[10px] font-medium text-flag/90"
                        title="These entities are not directly connected."
                      >
                        <Unlink size={11} />
                        no direct link
                      </span>
                      <EntityPill name={gap.target.name} type={gap.target.type} />
                    </div>
                    <div
                      className="mt-2 flex flex-wrap items-center gap-1.5"
                      title={`raw link-prediction score: ${gap.score.toFixed(3)}`}
                    >
                      <span className="h-1 w-20 rounded-full bg-ink-700">
                        <span
                          className="block h-full rounded-full"
                          style={{ width: `${strength.pct * 100}%`, backgroundColor: color }}
                        />
                      </span>
                      <Badge tone={strength.tier === "strong" ? "brass" : "neutral"} size="sm">
                        {strength.label}
                      </Badge>
                      <Badge tone="neutral" size="sm">
                        {gap.common_neighbor_count} shared{" "}
                        {gap.common_neighbor_count === 1 ? "intermediary" : "intermediaries"}
                      </Badge>
                      {gap.interdisciplinary && (
                        <Badge
                          tone="brass"
                          size="sm"
                          title="Connects two different topic clusters."
                        >
                          Community bridge
                        </Badge>
                      )}
                    </div>
                    <p
                      className="mt-2 overflow-hidden text-[11.5px] leading-relaxed text-faint"
                      style={{
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                      }}
                    >
                      {plainSummary(gap)}
                    </p>
                    {isSelected && (
                      <p className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-brass">
                        <Eye size={12} />
                        Shown on graph ->
                      </p>
                    )}
                  </div>
                </button>

                {isExpanded && (
                  <div className="border-t border-ink-700/70 px-3 pb-3 pt-2">
                    <SectionLabel>Shared intermediaries</SectionLabel>
                    <div className="flex flex-col gap-1.5">
                      {evidence.map((ev) => (
                        <div
                          key={ev.intermediary.name}
                          className="rounded-md border border-ink-700/70 bg-ink-850/55 px-2.5 py-2"
                        >
                          <div className="flex flex-wrap items-center gap-1.5 text-[10.5px]">
                            <EntityPill name={gap.source.name} type={gap.source.type} compact />
                            <span className="text-faint">-</span>
                            <RelationList rels={ev.source_relation_types} />
                            <span className="text-faint">-</span>
                            <EntityPill
                              name={ev.intermediary.name}
                              type={ev.intermediary.type}
                              compact
                            />
                            <span className="text-faint">-</span>
                            <RelationList rels={ev.target_relation_types} />
                            <span className="text-faint">-</span>
                            <EntityPill name={gap.target.name} type={gap.target.type} compact />
                          </div>
                        </div>
                      ))}
                    </div>
                    {gap.shared_intermediaries.length > 3 && (
                      <button
                        type="button"
                        onClick={() => toggleEvidence(key)}
                        className="mt-2 text-[11.5px] font-medium text-brass/80 hover:text-brass"
                      >
                        {evidenceOpen ? "Show fewer" : `Show all ${gap.shared_intermediaries.length}`}
                        {!evidenceOpen && hiddenEvidence > 0 ? ` (${hiddenEvidence} more)` : ""}
                      </button>
                    )}

                    <Button
                      variant="outline"
                      size="sm"
                      loading={generating === key}
                      onClick={() => handleGenerate(gap)}
                      className="mt-3 w-full"
                    >
                      Generate hypothesis
                    </Button>

                    {hypothesis && <HypothesisBlock hypothesis={hypothesis} />}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
