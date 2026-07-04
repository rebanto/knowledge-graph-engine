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
        className="inline-flex items-center gap-1 font-mono text-[11px] text-flag/90 hover:text-flag hover:underline"
      >
        {id} <ExternalLink size={9} />
      </a>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[11px] text-flag/80">
      <FileText size={9} /> {id.length > 32 ? `${id.slice(0, 32)}...` : id}
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
    <div className="rounded-xl border border-flag/25 bg-flag-dim p-4">
      <div className="mb-2.5 flex items-center gap-2">
        <AlertTriangle size={14} className="flex-shrink-0 text-flag" />
        <h3 className="text-[13px] font-semibold text-flag">
          {conflicts.length === 1
            ? "The sources disagree on one thing"
            : `The sources disagree on ${conflicts.length} things`}
        </h3>
      </div>
      <p className="mb-3 text-[12px] leading-relaxed text-flag/70">
        Opposite claims were found for the pairs below. Treat them as contested.
      </p>
      <ul className="flex flex-col gap-2">
        {conflicts.map((c, i) => (
          <li
            key={`${c.source}-${c.target}-${i}`}
            className="rounded-lg border border-flag/15 bg-ink-850 px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
              <span className="font-medium text-paper">{c.source}</span>
              <span className="text-flag/70">vs</span>
              <span className="font-medium text-paper">{c.target}</span>
              {c.claim_types.length > 0 && (
                <span className="flex flex-wrap gap-1">
                  {c.claim_types.map((t) => (
                    <span
                      key={t}
                      className="rounded-full border border-flag/25 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-flag/90"
                    >
                      {t}
                    </span>
                  ))}
                </span>
              )}
            </div>
            {c.documents.length > 0 && (
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span className="eyebrow text-faint">From</span>
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
