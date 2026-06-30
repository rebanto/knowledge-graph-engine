import { useMemo, useState } from "react";
import {
  AlertTriangle, Check, Clipboard, Download, FileSearch, GitBranch, Layers,
  ShieldCheck,
} from "lucide-react";
import type { QuestionResponse } from "../types";
import { TrustBadge } from "./TrustBadge";
import { Badge, Button, Card } from "./ui";

function pctLabel(report: QuestionResponse) {
  const total = report.graph_records.length + report.vector_chunks.length;
  if (total === 0) return "no evidence";
  const conflicted = report.conflicts?.length ?? 0;
  if (conflicted > 0) return `${conflicted} flagged`;
  return `${total} retrieved`;
}

function markdownReport(report: QuestionResponse) {
  const trust = report.trust ?? {
    score: null,
    supported: 0,
    total: 0,
    unsupported_claims: [],
  };
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
    `- Trust score: ${
      trust.score === null
        ? "n/a"
        : `${Math.round(trust.score * 100)}% (${trust.supported}/${trust.total} claims)`
    }`,
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
  const trust = report.trust ?? {
    score: null,
    supported: 0,
    total: 0,
    unsupported_claims: [],
  };

  async function copyMarkdown() {
    await navigator.clipboard.writeText(markdownReport(report));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 px-3.5 py-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <TrustBadge trust={trust} />
        <Badge
          tone={hasConflict ? "flag" : "ok"}
          title="Evidence pulled from graph records and source passages."
        >
          {hasConflict ? <AlertTriangle size={12} /> : <ShieldCheck size={12} />}
          {evidenceLabel}
        </Badge>
        <Badge tone="graph">
          <GitBranch size={12} /> {report.graph_records.length} graph
        </Badge>
        <Badge tone="vector">
          <FileSearch size={12} /> {report.vector_chunks.length} passages
        </Badge>
        {report.retrieval_type === "hybrid" && (
          <Badge tone="hybrid">
            <Layers size={12} /> merged
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={copyMarkdown}>
          {copied ? <Check size={13} className="text-ok" /> : <Clipboard size={13} />}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => downloadMarkdown(report)}>
          <Download size={13} /> Export
        </Button>
      </div>
    </Card>
  );
}
