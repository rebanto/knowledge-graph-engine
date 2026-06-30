import ReactMarkdown from "react-markdown";
import { Database } from "lucide-react";
import type { QuestionResponse } from "../types";
import { RoutingBadge } from "./RoutingBadge";
import { SourcesPanel } from "./SourcesPanel";
import { EntitySummary } from "./EntitySummary";
import { InsightCards } from "./InsightCards";
import { ConflictBanner } from "./ConflictBanner";
import { AnswerProofBar } from "./AnswerProofBar";
import { ClaimLedger } from "./ClaimLedger";

export function AnswerView({ report }: { report: QuestionResponse }) {
  const hasInsights = report.insights && report.insights.length > 0;
  const hasEntities = report.key_entities && report.key_entities.length > 0;
  const conflicts = report.conflicts ?? [];

  return (
    <div className="animate-fade-in flex flex-col gap-6">
      <div>
        <h1 className="font-display text-[26px] font-medium leading-[1.25] tracking-tight text-paper">
          {report.question}
        </h1>
        {report.standalone_question && (
          <p
            className="mt-2 text-[12.5px] italic text-faint"
            title="Your follow-up was resolved into this self-contained question before searching"
          >
            interpreted as: "{report.standalone_question}"
          </p>
        )}
        <div className="mt-3 flex items-center gap-2">
          <RoutingBadge type={report.retrieval_type} />
          {report.cached && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-ink-700 px-2 py-1 text-[11px] text-faint"
              title="Answered from cache"
            >
              <Database size={11} />
              from cache
            </span>
          )}
          {report.version > 1 && (
            <span className="font-mono text-[11px] text-faint" title="Re-run this many times">
              v{report.version}
            </span>
          )}
        </div>
      </div>

      <AnswerProofBar report={report} />

      {hasEntities && (
        <EntitySummary
          records={report.graph_records}
          retrieval_type={report.retrieval_type}
          key_entities={report.key_entities}
        />
      )}

      <div className="prose-answer text-[14.5px] leading-[1.78] text-paper-dim">
        <ReactMarkdown>{report.answer}</ReactMarkdown>
      </div>

      <ConflictBanner conflicts={conflicts} />

      <ClaimLedger trust={report.trust} />

      {hasInsights && <InsightCards insights={report.insights} />}

      {!hasEntities && (
        <EntitySummary records={report.graph_records} retrieval_type={report.retrieval_type} />
      )}

      <SourcesPanel
        cypher={report.cypher}
        graphRecords={report.graph_records}
        vectorChunks={report.vector_chunks}
      />
    </div>
  );
}
