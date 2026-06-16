import ReactMarkdown from "react-markdown";
import { Database } from "lucide-react";
import type { QuestionResponse } from "../types";
import { RoutingBadge } from "./RoutingBadge";
import { SourcesPanel } from "./SourcesPanel";

export function AnswerView({ report }: { report: QuestionResponse }) {
  return (
    <div className="animate-fade-in flex flex-col gap-5">
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
        {report.reasoning && (
          <p className="mt-2 text-[12.5px] italic text-zinc-600">{report.reasoning}</p>
        )}
      </div>

      <div className="prose-answer text-[14.5px] leading-[1.7] text-zinc-300">
        <ReactMarkdown>{report.answer}</ReactMarkdown>
      </div>

      <SourcesPanel
        cypher={report.cypher}
        graphRecords={report.graph_records}
        vectorChunks={report.vector_chunks}
      />
    </div>
  );
}
