import ReactMarkdown from "react-markdown";
import {
  AlertTriangle, Check, GitBranch, Layers, Search, Sparkles,
} from "lucide-react";
import type { DeepResearchResult, QuestionResponse, RetrievalRoute } from "../types";
import { Badge, Card } from "./ui";
import { ConflictBanner } from "./ConflictBanner";
import { TrustBadge } from "./TrustBadge";

type DeepReport = Pick<
  QuestionResponse | DeepResearchResult,
  "question" | "answer" | "subquestions" | "trust" | "conflicts" | "version"
>;

const ROUTE_ICON: Record<RetrievalRoute, typeof GitBranch> = {
  graph: GitBranch,
  vector: Search,
  hybrid: Layers,
};

const ROUTE_TONE: Record<RetrievalRoute, "graph" | "vector" | "hybrid"> = {
  graph: "graph",
  vector: "vector",
  hybrid: "hybrid",
};

const ROUTE_CLASS: Record<RetrievalRoute, string> = {
  graph: "text-graph",
  vector: "text-vector",
  hybrid: "text-hybrid",
};

export function DeepResearchReport({ report }: { report: DeepReport }) {
  const unsupported = report.trust?.unsupported_claims ?? [];
  const subquestions = report.subquestions ?? [];

  return (
    <div className="animate-fade-in flex flex-col gap-6">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge tone="brass">
            <Sparkles size={12} strokeWidth={2.25} />
            Deep Research
          </Badge>
          <TrustBadge trust={report.trust} />
          {report.version > 1 && (
            <span className="font-mono text-[11px] text-faint" title="Re-run this many times">
              v{report.version}
            </span>
          )}
        </div>
        <h1 className="font-display text-[26px] font-medium leading-[1.25] tracking-tight text-paper">
          {report.question}
        </h1>
      </div>

      <div className="prose-answer text-[15px] leading-[1.78] text-paper-dim">
        <ReactMarkdown>{report.answer}</ReactMarkdown>
      </div>

      <ConflictBanner conflicts={report.conflicts ?? []} />

      {unsupported.length > 0 && (
        <Card as="section" className="border-flag/30 bg-flag/5 p-3.5">
          <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium text-flag">
            <AlertTriangle size={12} />
            Claims the judge could not trace to retrieved data
          </p>
          <ul className="list-disc space-y-1 pl-5 text-[12px] text-paper-dim">
            {unsupported.map((claim, i) => <li key={`${claim}-${i}`}>{claim}</li>)}
          </ul>
        </Card>
      )}

      {subquestions.length > 0 && (
        <section className="flex flex-col gap-2.5">
          <h2 className="text-[11px] font-medium uppercase tracking-wider text-faint">
            Subquestion trace
          </h2>
          {subquestions.map((sub, i) => {
            const RouteIcon = ROUTE_ICON[sub.route] ?? Layers;
            const tone = ROUTE_TONE[sub.route] ?? "hybrid";
            const routeClass = ROUTE_CLASS[sub.route] ?? "text-hybrid";
            return (
              <Card key={`${sub.question}-${i}`} variant="flat" className="p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2">
                    <RouteIcon
                      size={14}
                      className={`mt-0.5 flex-shrink-0 ${routeClass}`}
                      strokeWidth={2.25}
                    />
                    <div className="min-w-0">
                      <div className="mb-1 flex flex-wrap items-center gap-1.5">
                        <Badge tone={tone} size="sm">{sub.route}</Badge>
                        {sub.error ? (
                          <Badge tone="flag" size="sm">
                            <AlertTriangle size={11} />
                            error
                          </Badge>
                        ) : (
                          <Badge tone="ok" size="sm">
                            <Check size={11} />
                            done
                          </Badge>
                        )}
                      </div>
                      <p className="text-[13px] font-medium leading-snug text-paper">
                        {sub.question}
                      </p>
                      {sub.why && <p className="mt-0.5 text-[12px] italic text-faint">{sub.why}</p>}
                    </div>
                  </div>
                </div>

                {sub.error ? (
                  <p className="mt-2.5 border-t border-ink-700/60 pt-2.5 text-[12px] text-flag">
                    {sub.error}
                  </p>
                ) : sub.answer ? (
                  <div className="prose-answer mt-2.5 border-t border-ink-700/60 pt-2.5 text-[13px] leading-[1.7] text-paper-dim">
                    <ReactMarkdown>{sub.answer}</ReactMarkdown>
                  </div>
                ) : null}
              </Card>
            );
          })}
        </section>
      )}
    </div>
  );
}
