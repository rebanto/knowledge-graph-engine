import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, CircleDot, Check, GitBranch, Search, Layers, Sparkles, AlertTriangle } from "lucide-react";
import { streamDeepResearch } from "../api";
import type {
  SubQuestionResult, SubAgentProgress, TrustScore, DeepResearchResult, RetrievalRoute,
} from "../types";
import { TrustBadge } from "./TrustBadge";
import { ConflictBanner } from "./ConflictBanner";
import { Badge, Card } from "./ui";

const ROUTE_ICON: Record<RetrievalRoute, typeof GitBranch> = {
  graph: GitBranch, vector: Search, hybrid: Layers,
};
const ROUTE_TONE: Record<RetrievalRoute, string> = {
  graph: "text-graph", vector: "text-vector", hybrid: "text-hybrid",
};

type Phase = "planning" | "researching" | "synthesizing" | "verifying" | "done" | "error";

const PHASES: { key: Phase; label: string }[] = [
  { key: "planning", label: "Plan" },
  { key: "researching", label: "Research" },
  { key: "synthesizing", label: "Synthesize" },
  { key: "verifying", label: "Verify" },
];

/**
 * Drives one multi-agent deep-research run and renders it live: the plan, each
 * sub-agent filling in as it finishes, then the fused answer with a faithfulness
 * trust score. Self-contained - it owns the SSE stream so App stays thin.
 */
export function DeepResearchPanel({
  question, workspaceId, onSaved,
}: {
  question: string;
  workspaceId: string;
  onSaved?: (conversationId: string) => void | Promise<void>;
}) {
  const [phase, setPhase] = useState<Phase>("planning");
  const [statusMsg, setStatusMsg] = useState("Planning...");
  const [plan, setPlan] = useState<SubQuestionResult[]>([]);
  const [agents, setAgents] = useState<Record<number, SubAgentProgress>>({});
  const [liveTrust, setLiveTrust] = useState<TrustScore | null>(null);
  const [result, setResult] = useState<DeepResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  // Reset the run's view state the moment the question/workspace changes
  // (render-time adjustment); starting the SSE stream stays in the effect.
  const [prevRun, setPrevRun] = useState({ question, workspaceId });
  if (prevRun.question !== question || prevRun.workspaceId !== workspaceId) {
    setPrevRun({ question, workspaceId });
    setPhase("planning"); setStatusMsg("Planning...");
    setPlan([]); setAgents({}); setLiveTrust(null); setResult(null); setError(null);
  }

  useEffect(() => {
    cancelRef.current?.();
    const cancel = streamDeepResearch(question, workspaceId, {
      onStatus: (p, message) => {
        setStatusMsg(message);
        if (p === "planning") setPhase("planning");
        else if (p === "synthesizing") setPhase("synthesizing");
        else if (p === "verifying") setPhase("verifying");
      },
      onPlan: (subs) => { setPlan(subs); setPhase("researching"); },
      onSubagent: (p) => setAgents((prev) => ({ ...prev, [p.index]: p })),
      onTrust: (t) => setLiveTrust(t),
      onDone: (r) => {
        setResult(r);
        setPhase("done");
        if (r.conversation_id) void onSaved?.(r.conversation_id);
      },
      onError: (detail) => { setError(detail); setPhase("error"); },
    });
    cancelRef.current = cancel;
    return () => cancel();
  }, [question, workspaceId, onSaved]);

  const activeIdx = PHASES.findIndex((p) => p.key === phase);

  return (
    <div className="animate-fade-in flex flex-col gap-6">
      {/* Header */}
      <div>
        <Badge tone="brass" className="mb-2">
          <Sparkles size={12} strokeWidth={2.25} /> Deep Research
        </Badge>
        <h1 className="font-display text-[26px] font-medium leading-[1.25] tracking-tight text-paper">
          {question}
        </h1>
      </div>

      {/* Phase rail */}
      <div className="flex items-center gap-2">
        {PHASES.map((p, i) => {
          const state = phase === "error" ? (i <= activeIdx ? "done" : "todo")
            : i < activeIdx || phase === "done" ? "done"
            : i === activeIdx ? "active" : "todo";
          return (
            <div key={p.key} className="flex items-center gap-2">
              <span className={`inline-flex items-center gap-1.5 text-[12px] ${
                state === "done" ? "text-graph" : state === "active" ? "text-brass" : "text-faint"
              }`}>
                {state === "done" ? <Check size={13} strokeWidth={2.5} />
                  : state === "active" ? <Loader2 size={13} className="animate-spin" />
                  : <CircleDot size={13} />}
                {p.label}
              </span>
              {i < PHASES.length - 1 && <span className="h-px w-5 bg-ink-700" />}
            </div>
          );
        })}
      </div>

      {phase !== "done" && phase !== "error" && (
        <p className="flex items-center gap-1.5 text-[12px] text-brass/80">
          <Loader2 size={11} className="animate-spin" /> {statusMsg}
        </p>
      )}
      {error && (
        <p className="flex items-center gap-1.5 text-[12px] text-flag">
          <AlertTriangle size={12} /> {error}
        </p>
      )}

      {/* Sub-agent cards */}
      {plan.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <h2 className="text-[11px] font-medium uppercase tracking-wider text-faint">
            {plan.length} research {plan.length === 1 ? "agent" : "agents"}
          </h2>
          {plan.map((sub, i) => {
            const live = agents[i];
            const done = live?.status === "done";
            const RouteIcon = ROUTE_ICON[sub.route] ?? Layers;
            return (
              <Card key={i} variant="flat" className="p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2">
                    <RouteIcon size={14} className={`mt-0.5 flex-shrink-0 ${ROUTE_TONE[sub.route]}`} strokeWidth={2.25} />
                    <div>
                      <p className="text-[13px] font-medium leading-snug text-paper">{sub.question}</p>
                      {sub.why && <p className="mt-0.5 text-[12px] italic text-faint">{sub.why}</p>}
                    </div>
                  </div>
                  <span className="flex-shrink-0">
                    {done ? <Check size={14} className="text-graph" strokeWidth={2.5} />
                      : live?.status === "running" ? <Loader2 size={14} className="animate-spin text-brass" />
                      : <CircleDot size={14} className="text-faint" />}
                  </span>
                </div>
                {done && live?.answer && (
                  <div className="prose-answer mt-2.5 border-t border-ink-700/60 pt-2.5 text-[13px] leading-[1.7] text-paper-dim">
                    <ReactMarkdown>{live.answer}</ReactMarkdown>
                  </div>
                )}
                {done && live?.evidence && (
                  <p className="mt-2 font-mono text-[11px] text-faint">
                    {live.evidence.graph_records} graph records, {live.evidence.passages} passages
                    {live.evidence.conflicts > 0 && `, ${live.evidence.conflicts} conflicts`}
                  </p>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* Final fused report */}
      {result && (
        <div className="flex flex-col gap-4 border-t border-ink-700 pt-6">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-display text-[17px] font-medium text-paper">Synthesized answer</h2>
            <TrustBadge trust={result.trust} />
          </div>
          <div className="prose-answer text-[15px] leading-[1.78] text-paper-dim">
            <ReactMarkdown>{result.answer}</ReactMarkdown>
          </div>

          <ConflictBanner conflicts={result.conflicts ?? []} />

          {/* Unsupported claims from verification */}
                {result.trust.unsupported_claims.length > 0 && (
            <div className="rounded-xl border border-flag/30 bg-flag/5 p-3.5">
              <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium text-flag">
                <AlertTriangle size={12} /> Unsupported claims
              </p>
              <ul className="list-disc space-y-1 pl-5 text-[12px] text-paper-dim">
                {result.trust.unsupported_claims.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Live trust preview before the done frame lands */}
      {!result && liveTrust && (
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-faint">Verifying:</span>
          <TrustBadge trust={liveTrust} size="sm" />
        </div>
      )}
    </div>
  );
}
