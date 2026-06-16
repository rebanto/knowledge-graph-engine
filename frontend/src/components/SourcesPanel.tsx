import { useState } from "react";
import { ChevronDown, FileText } from "lucide-react";
import type { GraphRecord, VectorChunk } from "../types";

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
    <div className="border-t border-zinc-800/60">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-3 text-left"
      >
        <span className="text-[13px] font-medium text-zinc-400">
          {title} <span className="text-zinc-600">({count})</span>
        </span>
        <ChevronDown
          size={15}
          className={`text-zinc-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="pb-4">{children}</div>}
    </div>
  );
}

function GraphTable({ records }: { records: GraphRecord[] }) {
  const columns = Object.keys(records[0] ?? {});
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-800/60">
      <table className="w-full text-left text-[12.5px]">
        <thead>
          <tr className="border-b border-zinc-800/60 bg-zinc-900/40">
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 font-medium text-zinc-500">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((row, i) => (
            <tr key={i} className="border-b border-zinc-900 last:border-0">
              {columns.map((col) => (
                <td key={col} className="px-3 py-2 font-mono text-zinc-300">
                  {String(row[col] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: VectorChunk }) {
  const relevance = Math.max(0, Math.min(100, Math.round((1 - chunk.distance / 2) * 100)));
  return (
    <div className="rounded-lg border border-zinc-800/60 bg-zinc-900/30 p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-zinc-300">
          <FileText size={12} className="text-zinc-500" />
          {chunk.source_title ?? "Untitled source"}
        </div>
        <span className="flex-shrink-0 font-mono text-[11px] text-zinc-600">{relevance}% match</span>
      </div>
      <p className="text-[12.5px] leading-relaxed text-zinc-500">{chunk.text}</p>
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
        <Disclosure title="Cypher query" count={1}>
          <pre className="overflow-x-auto rounded-lg border border-zinc-800/60 bg-zinc-900/40 p-3 font-mono text-[12px] leading-relaxed text-zinc-400">
            {cypher}
          </pre>
        </Disclosure>
      )}
      <Disclosure title="Graph results" count={graphRecords.length}>
        <GraphTable records={graphRecords} />
      </Disclosure>
      <Disclosure title="Source passages" count={vectorChunks.length}>
        <div className="flex flex-col gap-2">
          {vectorChunks.map((chunk, i) => (
            <ChunkCard key={i} chunk={chunk} />
          ))}
        </div>
      </Disclosure>
    </div>
  );
}
