import { ArrowRight } from "lucide-react";
import type { GraphRecord, KeyEntity } from "../types";
import { nodeColor } from "../lib/palette";
import { Card } from "./ui";

// ── Fallback parser for legacy / no-key_entities responses ───────────────────
const KNOWN_REL_TYPES = new Set([
  "AUTHORED","CITED","FUNDED_BY","COLLABORATED_WITH",
  "PUBLISHED_IN","SUPPORTS","CONTRADICTS","CONFLICTS_WITH",
]);

function isRelType(v: unknown): v is string {
  return typeof v === "string" && KNOWN_REL_TYPES.has(v);
}
function isEntityName(v: unknown): v is string {
  if (typeof v !== "string") return false;
  if (KNOWN_REL_TYPES.has(v) || v.startsWith("http") || /^\d{4}\.\d/.test(v)) return false;
  return v.trim().length > 0 && v.length < 120;
}

function parseRecordsFallback(records: GraphRecord[]) {
  if (!records.length) return { relTypes: [] as string[], entityCount: 0, paths: [] as Array<{from:string;rel:string;to:string}> };
  const cols = Object.keys(records[0]);
  const relCols = cols.filter((c) => records.some((r) => isRelType(r[c])));
  const entityCols = cols.filter((c) => !relCols.includes(c) && records.some((r) => isEntityName(r[c])));
  const relTypes = Array.from(new Set(records.flatMap((r) => cols.map((c) => r[c])).filter(isRelType)));
  const entityCount = new Set(records.flatMap((r) => entityCols.map((c) => r[c])).filter(isEntityName)).size;
  const paths: Array<{from:string;rel:string;to:string}> = [];
  if (entityCols.length >= 2 && relCols.length >= 1) {
    const seen = new Set<string>();
    for (const r of records) {
      const from = r[entityCols[0]], to = r[entityCols[1]], rel = r[relCols[0]];
      if (isEntityName(from) && isEntityName(to) && isRelType(rel)) {
        const key = `${from}::${rel}::${to}`;
        if (!seen.has(key)) { seen.add(key); paths.push({ from, rel, to }); }
      }
    }
  }
  return { relTypes, entityCount, paths };
}

// ── Component ────────────────────────────────────────────────────────────────
interface Props {
  records: GraphRecord[];
  retrieval_type: string;
  key_entities?: KeyEntity[];
}

export function EntitySummary({ records, retrieval_type, key_entities = [] }: Props) {
  // Primary path: structured key_entities from backend
  if (key_entities.length > 0) {
    return (
      <div className="flex flex-wrap gap-2">
        {key_entities.map((e, i) => {
          const color = nodeColor(e.type);
          return (
            <div
              key={i}
              className="flex items-start gap-2 rounded-lg border px-3 py-2"
              style={{ borderColor: `${color}30`, backgroundColor: `${color}0d` }}
              title={e.role}
            >
              <span
                className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full"
                style={{ backgroundColor: color }}
              />
              <div className="min-w-0">
                <p className="truncate text-[12px] font-medium" style={{ color }}>
                  {e.name}
                </p>
                <p className="text-[11px] text-faint">{e.type}</p>
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  // Fallback: heuristic parsing from raw records (no key_entities returned)
  if (!records.length || retrieval_type === "vector") return null;
  const { relTypes, entityCount, paths } = parseRecordsFallback(records);
  if (relTypes.length === 0 && entityCount === 0) return null;

  const visible = paths.slice(0, 5);
  const extra = paths.length - visible.length;

  return (
    <Card variant="flat" className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-muted">
        <span><span className="font-medium text-paper-dim">{records.length}</span> results</span>
        {entityCount > 0 && <span><span className="font-medium text-paper-dim">{entityCount}</span> entities</span>}
        {relTypes.length > 0 && (
          <span className="flex flex-wrap items-center gap-1">
            via
            {relTypes.map((t) => (
              <span key={t} className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-[10px] text-muted">{t}</span>
            ))}
          </span>
        )}
      </div>
      {visible.length > 0 && (
        <div className="flex flex-col gap-2">
          {visible.map((p, i) => (
            <div key={i} className="flex min-w-0 items-center gap-1.5">
              <span className="max-w-[180px] truncate rounded-md bg-ink-700 px-2 py-1 text-[12px] text-paper-dim">{p.from}</span>
              <span className="flex-shrink-0 rounded bg-ink-750 px-1.5 py-0.5 font-mono text-[10px] text-faint">{p.rel}</span>
              <ArrowRight size={12} className="flex-shrink-0 text-brass" />
              <span className="max-w-[180px] truncate rounded-md bg-ink-700 px-2 py-1 text-[12px] text-paper-dim">{p.to}</span>
            </div>
          ))}
          {extra > 0 && <p className="text-[11px] text-faint">+{extra} more</p>}
        </div>
      )}
    </Card>
  );
}
