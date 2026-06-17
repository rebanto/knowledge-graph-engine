import ReactMarkdown from "react-markdown";
import { Database } from "lucide-react";
import type { QuestionResponse } from "../types";
import { RoutingBadge } from "./RoutingBadge";
import { SourcesPanel } from "./SourcesPanel";
import { EntitySummary } from "./EntitySummary";
import { InsightCards } from "./InsightCards";

export function AnswerView({ report }: { report: QuestionResponse }) {
  const hasInsights = report.insights && report.insights.length > 0;
  const hasEntities = report.key_entities && report.key_entities.length > 0;

  return (
    <div className="animate-fade-in flex flex-col gap-6">

      {/* Header */}
      <div>
        <h1 className="text-[20px] font-semibold leading-snug tracking-tight text-zinc-100">
          {report.question}
        </h1>
        <div className="mt-2.5 flex items-center gap-2">
          <RoutingBadge type={report.retrieval_type} />
          {report.cached && (
            <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1 text-[11px] text-zinc-500">
              <Database size={11} />
              cached
            </span>
          )}
          {report.version > 1 && (
            <span className="font-mono text-[11px] text-zinc-600">v{report.version}</span>
          )}
        </div>
      </div>

      {/* Key entities row — shown when backend returns structured entities */}
      {hasEntities && (
        <EntitySummary
          records={report.graph_records}
          retrieval_type={report.retrieval_type}
          key_entities={report.key_entities}
        />
      )}

      {/* Prose answer */}
      <div className="prose-answer text-[14.5px] leading-[1.75] text-zinc-300">
        <ReactMarkdown>{report.answer}</ReactMarkdown>
      </div>

      {/* Visual insights — charts, flows, timelines */}
      {hasInsights && <InsightCards insights={report.insights} />}

      {/* Fallback entity summary when no structured entities */}
      {!hasEntities && (
        <EntitySummary
          records={report.graph_records}
          retrieval_type={report.retrieval_type}
        />
      )}

      {/* Collapsible source details */}
      <SourcesPanel
        cypher={report.cypher}
        graphRecords={report.graph_records}
        vectorChunks={report.vector_chunks}
      />
    </div>
  );
}
