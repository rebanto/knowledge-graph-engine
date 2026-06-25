import { AlertTriangle, FileText, ExternalLink } from "lucide-react";
import type { Conflict } from "../types";

const ARXIV_ID_PATTERN = /^\d{4}\.\d{4,5}(v\d+)?$/;

function DocumentRef({ id }: { id: string }) {
  if (ARXIV_ID_PATTERN.test(id)) {
    return (
      <a
        href={`https://arxiv.org/abs/${id}`}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 font-mono text-[11px] text-rose-300/80 hover:text-rose-200 hover:underline"
      >
        {id} <ExternalLink size={9} />
      </a>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[11px] text-rose-300/70">
      <FileText size={9} /> {id.length > 32 ? `${id.slice(0, 32)}…` : id}
    </span>
  );
}

/**
 * Surfaces disputed claims the graph retriever flagged: two sources making
 * opposite SUPPORTS/CONTRADICTS assertions about the same pair of entities.
 * Renders nothing when there are no conflicts, so it's safe to always mount.
 */
export function ConflictBanner({ conflicts }: { conflicts: Conflict[] }) {
  if (!conflicts || conflicts.length === 0) return null;

  return (
    <div className="rounded-xl border border-rose-500/25 bg-rose-500/[0.06] p-4">
      <div className="mb-2.5 flex items-center gap-2">
        <AlertTriangle size={14} className="flex-shrink-0 text-rose-400" />
        <h3 className="text-[13px] font-semibold text-rose-300">
          {conflicts.length === 1
            ? "1 disputed claim in the sources"
            : `${conflicts.length} disputed claims in the sources`}
        </h3>
      </div>
      <p className="mb-3 text-[12px] leading-relaxed text-rose-200/60">
        Different sources make conflicting assertions about these entity pairs.
        The answer above flags them; weigh the evidence rather than treating
        either as settled.
      </p>
      <ul className="flex flex-col gap-2">
        {conflicts.map((c, i) => (
          <li
            key={`${c.source}-${c.target}-${i}`}
            className="rounded-lg border border-rose-500/15 bg-rose-950/20 px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
              <span className="font-medium text-zinc-200">{c.source}</span>
              <span className="text-rose-400/70">⟷</span>
              <span className="font-medium text-zinc-200">{c.target}</span>
              {c.claim_types.length > 0 && (
                <span className="flex flex-wrap gap-1">
                  {c.claim_types.map((t) => (
                    <span
                      key={t}
                      className="rounded-full border border-rose-500/25 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-rose-300/80"
                    >
                      {t}
                    </span>
                  ))}
                </span>
              )}
            </div>
            {c.documents.length > 0 && (
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span className="text-[10.5px] text-zinc-600">sources:</span>
                {c.documents.map((d) => (
                  <DocumentRef key={d} id={d} />
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
