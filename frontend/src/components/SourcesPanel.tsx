import { useState } from "react";
import { ChevronDown, FileText, AlertTriangle, ExternalLink } from "lucide-react";
import type { GraphRecord, VectorChunk } from "../types";

const ARXIV_ID_PATTERN = /^\d{4}\.\d{4,5}(v\d+)?$/;

function arxivUrl(id: string): string {
  return `https://arxiv.org/abs/${id}`;
}

function CellValue({ column, value }: { column: string; value: GraphRecord[string] }) {
  const str = String(value ?? "—");

  if (column.toLowerCase().includes("url") && typeof value === "string" && value.startsWith("http")) {
    return (
      <a
        href={value}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 text-brass hover:underline"
      >
        source <ExternalLink size={10} />
      </a>
    );
  }

  if (
    (column.toLowerCase().includes("arxiv_id") || column.toLowerCase().includes("source_document_id")) &&
    typeof value === "string" &&
    ARXIV_ID_PATTERN.test(value)
  ) {
    return (
      <a
        href={arxivUrl(value)}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 text-brass hover:underline"
      >
        {value} <ExternalLink size={10} />
      </a>
    );
  }

  return <>{str}</>;
}

function Disclosure({
  title,
  count,
  children,
  defaultOpen = false,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (count === 0) return null;

  return (
    <div className="border-t border-ink-700">
      <button
        onClick={() => setOpen(!open)}
        className="group flex w-full items-center justify-between py-3 text-left"
      >
        <span className="text-[13px] font-medium text-muted group-hover:text-paper-dim">
          {title} <span className="text-faint">({count})</span>
        </span>
        <ChevronDown
          size={15}
          className={`text-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="pb-4">{children}</div>}
    </div>
  );
}

function isConflictRow(row: GraphRecord): boolean {
  return Object.entries(row).some(
    ([key, value]) => key.toLowerCase().includes("conflict") && value === true,
  );
}

function GraphTable({ records }: { records: GraphRecord[] }) {
  const columns = Object.keys(records[0] ?? {});
  return (
    <div className="overflow-x-auto rounded-lg border border-ink-700">
      <table className="w-full text-left text-[12.5px]">
        <thead>
          <tr className="border-b border-ink-700 bg-ink-800">
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 font-mono text-[11px] font-medium uppercase tracking-wide text-faint">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((row, i) => {
            const conflict = isConflictRow(row);
            return (
              <tr
                key={i}
                className={`border-b border-ink-800 last:border-0 ${conflict ? "bg-flag-dim" : ""}`}
              >
                {columns.map((col, ci) => (
                  <td key={col} className="px-3 py-2 font-mono text-paper-dim">
                    <div className="flex items-center gap-1.5">
                      {ci === 0 && conflict && (
                        <AlertTriangle size={11} className="flex-shrink-0 text-flag" />
                      )}
                      <CellValue column={col} value={row[col]} />
                    </div>
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: VectorChunk }) {
  const relevance = Math.max(0, Math.min(100, Math.round((1 - chunk.distance / 2) * 100)));
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-800/50 p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        {chunk.source_url ? (
          <a
            href={chunk.source_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-[12.5px] font-medium text-paper-dim hover:text-brass hover:underline"
          >
            <FileText size={12} className="flex-shrink-0 text-muted" />
            {chunk.source_title ?? "Untitled source"}
            <ExternalLink size={10} className="flex-shrink-0" />
          </a>
        ) : (
          <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-paper-dim">
            <FileText size={12} className="text-muted" />
            {chunk.source_title ?? "Untitled source"}
          </div>
        )}
        <span className="flex-shrink-0 font-mono text-[11px] text-faint">{relevance}% match</span>
      </div>
      <p className="text-[12.5px] leading-relaxed text-muted">{chunk.text}</p>
    </div>
  );
}

interface SourcesPanelProps {
  cypher: string | null;
  graphRecords: GraphRecord[];
  vectorChunks: VectorChunk[];
}

export function SourcesPanel({ cypher, graphRecords, vectorChunks }: SourcesPanelProps) {
  if (!cypher && graphRecords.length === 0 && vectorChunks.length === 0) return null;

  return (
    <div className="mt-2">
      {cypher && (
        <Disclosure title="The Cypher it ran" count={1}>
          <pre className="overflow-x-auto rounded-lg border border-ink-700 bg-ink-850 p-3 font-mono text-[12px] leading-relaxed text-paper-dim">
            {cypher}
          </pre>
        </Disclosure>
      )}
      <Disclosure title="Graph records" count={graphRecords.length}>
        <GraphTable records={graphRecords} />
      </Disclosure>
      <Disclosure title="Passages it read" count={vectorChunks.length}>
        <div className="flex flex-col gap-2">
          {vectorChunks.map((chunk, i) => (
            <ChunkCard key={i} chunk={chunk} />
          ))}
        </div>
      </Disclosure>
    </div>
  );
}
