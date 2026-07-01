import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, GitPullRequest, Loader2, Network } from "lucide-react";
import { fetchGaps, generateHypothesis } from "../api";
import type { Hypothesis, ResearchGap } from "../types";
import { Badge, Button, Card, SectionLabel } from "./ui";
import { BRASS, NODE_COLOR, NODE_FALLBACK } from "../lib/palette";

function gapKey(gap: ResearchGap) {
  return `${gap.source.name}::${gap.target.name}`;
}

function EntityPill({ name, type }: { name: string; type?: string | null }) {
  const color = type ? NODE_COLOR[type] ?? NODE_FALLBACK : NODE_FALLBACK;
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] font-medium"
      style={{ borderColor: `${color}42`, backgroundColor: `${color}14`, color }}
    >
      <span className="truncate">{name}</span>
      {type && <span className="font-mono text-[9.5px] opacity-60">{type}</span>}
    </span>
  );
}

function RelationList({ rels }: { rels: string[] }) {
  if (rels.length === 0) return <span className="text-faint">linked</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {rels.map((rel) => (
        <span
          key={rel}
          className="rounded px-1.5 py-0.5 font-mono text-[9.5px]"
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
}

export function ResearchGaps({ workspaceId, selectedGap, onSelectGap }: ResearchGapsProps) {
  const [gaps, setGaps] = useState<ResearchGap[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hypotheses, setHypotheses] = useState<Record<string, Hypothesis>>({});
  const [generating, setGenerating] = useState<string | null>(null);

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

  return (
    <aside className="flex h-full w-[380px] flex-shrink-0 flex-col border-r border-ink-700 bg-ink-900/45">
      <div className="border-b border-ink-700/70 px-4 py-3.5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <SectionLabel>Research Gaps</SectionLabel>
            <p className="mt-1 text-[11.5px] text-faint">Ranked missing links from graph structure</p>
          </div>
          <Badge tone="neutral" size="sm">{gaps.length}</Badge>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3 scrollbar-thin">
        {loading && (
          <div className="flex items-center gap-2 px-2 py-3 text-[12px] text-muted">
            <Loader2 size={14} className="animate-spin text-brass" />
            Finding open triangles
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

        <div className="flex flex-col gap-2">
          {gaps.map((gap) => {
            const key = gapKey(gap);
            const isExpanded = expanded === key;
            const isSelected = selectedGap && gapKey(selectedGap) === key;
            const hypothesis = hypotheses[key];
            return (
              <Card
                key={key}
                variant="flat"
                className={`overflow-hidden transition-colors ${
                  isSelected ? "border-brass/35 bg-brass-dim" : ""
                }`}
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
                      <EntityPill name={gap.source.name} type={gap.source.type} />
                      <span className="font-mono text-[12px] text-faint">...</span>
                      <EntityPill name={gap.target.name} type={gap.target.type} />
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge tone="neutral" size="sm">
                        {gap.common_neighbor_count} shared
                      </Badge>
                      {gap.interdisciplinary && <Badge tone="brass" size="sm">Community bridge</Badge>}
                      <span className="font-mono text-[10px] text-faint">
                        score {gap.score.toFixed(3)}
                      </span>
                    </div>
                  </div>
                </button>

                {isExpanded && (
                  <div className="border-t border-ink-700/70 px-3 pb-3 pt-2">
                    <p className="mb-2 text-[11.5px] leading-relaxed text-faint">
                      {gap.why_notable}
                    </p>
                    <div className="flex flex-col gap-1.5">
                      {gap.shared_intermediaries.map((ev) => (
                        <div
                          key={ev.intermediary.name}
                          className="rounded-md border border-ink-700/70 bg-ink-850/55 px-2.5 py-2"
                        >
                          <EntityPill
                            name={ev.intermediary.name}
                            type={ev.intermediary.type}
                          />
                          <div className="mt-1.5 grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-[10.5px]">
                            <RelationList rels={ev.source_relation_types} />
                            <GitPullRequest size={12} className="text-faint" />
                            <RelationList rels={ev.target_relation_types} />
                          </div>
                        </div>
                      ))}
                    </div>

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
