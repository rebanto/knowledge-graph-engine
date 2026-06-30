import { useMemo, useState } from "react";
import {
  AlertTriangle, Check, Clipboard, Download, FileSearch, GitBranch, Layers,
  ShieldCheck,
} from "lucide-react";
import type { QuestionResponse } from "../types";

function pctLabel(report: QuestionResponse) {
  const total = report.graph_records.length + report.vector_chunks.length;
  if (total === 0) return "no evidence";
  const conflicted = report.conflicts?.length ?? 0;
  if (conflicted > 0) return `${conflicted} flagged`;
  return `${total} retrieved`;
}

function markdownReport(report: QuestionResponse) {
  const lines = [
    `# ${report.question}`,
    "",
    report.answer,
    "",
    "## Retrieval",
    "",
    `- Route: ${report.retrieval_type}`,
    `- Version: ${report.version}`,
    `- Graph records: ${report.graph_records.length}`,
    `- Passages: ${report.vector_chunks.length}`,
    `- Conflicts: ${report.conflicts?.length ?? 0}`,
  ];

  if (report.cypher) {
    lines.push("", "## Cypher", "", "```cypher", report.cypher, "```");
  }

  if (report.vector_chunks.length > 0) {
    lines.push("", "## Passages");
    report.vector_chunks.forEach((chunk, index) => {
      lines.push(
        "",
        `${index + 1}. ${chunk.source_title ?? "Untitled source"}`,
        chunk.source_url ? `   ${chunk.source_url}` : "",
        `   ${chunk.text}`,
      );
    });
  }

  return lines.join("\n");
}

function downloadMarkdown(report: QuestionResponse) {
  const blob = new Blob([markdownReport(report)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${report.question.slice(0, 54).replace(/[^\w]+/g, "-").replace(/^-|-$/g, "") || "lattice-report"}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function AnswerProofBar({ report }: { report: QuestionResponse }) {
  const [copied, setCopied] = useState(false);
  const evidenceLabel = useMemo(() => pctLabel(report), [report]);
  const hasConflict = (report.conflicts?.length ?? 0) > 0;

  async function copyMarkdown() {
    await navigator.clipboard.writeText(markdownReport(report));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="surface flex flex-wrap items-center justify-between gap-3 rounded-xl px-3.5 py-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${
            hasConflict
              ? "border-flag/30 bg-flag/10 text-flag"
              : "border-ok/25 bg-ok-dim text-ok"
          }`}
          title="Evidence pulled from graph records and source passages."
        >
          {hasConflict ? <AlertTriangle size={12} /> : <ShieldCheck size={12} />}
          {evidenceLabel}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-graph/25 bg-graph-dim px-2.5 py-1 text-[11px] font-medium text-graph">
          <GitBranch size={12} /> {report.graph_records.length} graph
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-vector/25 bg-vector-dim px-2.5 py-1 text-[11px] font-medium text-vector">
          <FileSearch size={12} /> {report.vector_chunks.length} passages
        </span>
        {report.retrieval_type === "hybrid" && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-hybrid/25 bg-hybrid-dim px-2.5 py-1 text-[11px] font-medium text-hybrid">
            <Layers size={12} /> merged
          </span>
        )}
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={copyMarkdown}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11.5px] text-muted transition-colors hover:bg-ink-750 hover:text-paper-dim"
        >
          {copied ? <Check size={13} className="text-ok" /> : <Clipboard size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
        <button
          onClick={() => downloadMarkdown(report)}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11.5px] text-muted transition-colors hover:bg-ink-750 hover:text-paper-dim"
        >
          <Download size={13} /> Export
        </button>
      </div>
    </div>
  );
}
