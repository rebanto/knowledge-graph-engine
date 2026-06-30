import {
  Activity, AlertTriangle, ArrowUpRight, BookOpen, FileText, Globe, Network,
  RadioTower, Search, ShieldCheck, Sparkles,
} from "lucide-react";
import type { ConversationSummary, Workspace } from "../types";
import { Card, SectionLabel } from "./ui";

export interface SourceStats {
  total: number;
  ready: number;
  active: number;
  error: number;
  arxiv: number;
  rss: number;
  web: number;
  pdf: number;
}

const MODE_CARDS = [
  {
    label: "Proof Brief",
    detail: "answer + checked claim ledger",
    Icon: ShieldCheck,
    prompt: "Write a proof brief: strongest supported claims, weak claims, and the source evidence behind each.",
  },
  {
    label: "Connection Trace",
    detail: "multi-hop graph reasoning",
    Icon: Network,
    prompt: "Trace the most important relationships between the central people, papers, and concepts.",
  },
  {
    label: "Disagreement Audit",
    detail: "conflicts and weak claims",
    Icon: AlertTriangle,
    prompt: "Where do the sources disagree, and which claims should be treated cautiously?",
  },
  {
    label: "Agent Context Pack",
    detail: "portable grounded memory",
    Icon: Search,
    prompt: "Prepare a compact, source-grounded context pack another AI agent could use safely.",
  },
];

function readiness(stats: SourceStats | null) {
  if (!stats || stats.total === 0) return { label: "No corpus", tone: "text-faint", pct: 0 };
  const pct = Math.round((stats.ready / stats.total) * 100);
  if (stats.error > 0) return { label: `${pct}% ready`, tone: "text-flag", pct };
  if (stats.active > 0) return { label: `${pct}% ready`, tone: "text-brass", pct };
  return { label: "Ready", tone: "text-ok", pct: 100 };
}

function sourceMix(stats: SourceStats | null) {
  if (!stats || stats.total === 0) return "No sources";
  const parts = [
    stats.arxiv > 0 && `${stats.arxiv} arxiv`,
    stats.rss > 0 && `${stats.rss} feed${stats.rss === 1 ? "" : "s"}`,
    stats.web > 0 && `${stats.web} web`,
    stats.pdf > 0 && `${stats.pdf} pdf`,
  ].filter(Boolean);
  return parts.join(" / ");
}

function StatTile({
  label,
  value,
  hint,
  Icon,
  tone = "text-brass",
}: {
  label: string;
  value: string | number;
  hint: string;
  Icon: typeof Activity;
  tone?: string;
}) {
  return (
    <Card className="px-3.5 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <SectionLabel>{label}</SectionLabel>
        <Icon size={13} className={tone} />
      </div>
      <p className="font-display text-[20px] leading-none text-paper">{value}</p>
      <p className="mt-1 text-[12px] leading-snug text-faint">{hint}</p>
    </Card>
  );
}

export function WorkspacePulse({
  workspace,
  stats,
  conversations,
  suggestedQuestions,
  onPick,
  onGoToSources,
  onGoToGraph,
}: {
  workspace: Workspace | null;
  stats: SourceStats | null;
  conversations: ConversationSummary[];
  suggestedQuestions: string[];
  onPick: (question: string) => void;
  onGoToSources: () => void;
  onGoToGraph: () => void;
}) {
  const r = readiness(stats);
  const hasSources = (stats?.total ?? 0) > 0;
  const hasGraph = (stats?.ready ?? 0) > 0;

  return (
    <div className="mt-7 grid w-full gap-4 lg:grid-cols-[1.05fr_0.95fr]">
      <Card variant="raised" as="section" className="p-4">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <SectionLabel>Workspace Pulse</SectionLabel>
            <h2 className="mt-1 truncate font-display text-[19px] font-medium text-paper">
              {workspace?.name ?? "Untitled workspace"}
            </h2>
            <p className="mt-1 text-[12px] text-muted">{workspace?.domain ?? "Research"}</p>
          </div>
          <div className="min-w-[92px]">
            <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full rounded-full bg-brass transition-all duration-500"
                style={{ width: `${r.pct}%` }}
              />
            </div>
            <p className={`mt-1 text-right font-mono text-[10.5px] ${r.tone}`}>{r.label}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <StatTile
            label="Corpus"
            value={stats?.total ?? 0}
            hint={sourceMix(stats)}
            Icon={BookOpen}
            tone={hasSources ? "text-brass" : "text-faint"}
          />
          <StatTile
            label="Ready"
            value={stats?.ready ?? 0}
            hint={stats?.active ? `${stats.active} still reading` : "searchable now"}
            Icon={RadioTower}
            tone={stats?.active ? "text-brass" : "text-ok"}
          />
          <StatTile
            label="Threads"
            value={conversations.length}
            hint={conversations.length ? "saved research trails" : "no questions yet"}
            Icon={Sparkles}
            tone="text-hybrid"
          />
          <StatTile
            label="Graph"
            value={hasGraph ? "live" : "quiet"}
            hint={hasGraph ? "entities available" : "waiting for sources"}
            Icon={Network}
            tone={hasGraph ? "text-vector" : "text-faint"}
          />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={onGoToSources}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ink-700 px-3 py-1.5 text-[12px] text-muted transition-colors hover:border-brass/35 hover:text-paper-dim"
          >
            <FileText size={12} /> Sources
          </button>
          <button
            onClick={onGoToGraph}
            disabled={!hasGraph}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ink-700 px-3 py-1.5 text-[12px] text-muted transition-colors hover:border-brass/35 hover:text-paper-dim disabled:opacity-35"
          >
            <Globe size={12} /> Graph
          </button>
        </div>
      </Card>

      <Card variant="raised" as="section" className="p-4">
        <SectionLabel>Research Moves</SectionLabel>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {MODE_CARDS.map(({ label, detail, Icon, prompt }) => (
            <button
              key={label}
              onClick={() => onPick(prompt)}
              disabled={!hasSources}
              className="group min-h-[86px] rounded-lg border border-ink-700 bg-ink-800/35 p-3 text-left transition-colors hover:border-brass/35 hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <Icon size={14} className="text-brass/80" />
                <ArrowUpRight size={13} className="text-ghost transition-colors group-hover:text-brass" />
              </div>
              <p className="text-[13px] font-medium text-paper-dim group-hover:text-paper">{label}</p>
              <p className="mt-0.5 text-[12px] leading-snug text-faint">{detail}</p>
            </button>
          ))}
        </div>

        {suggestedQuestions.length > 0 && (
          <div className="mt-4 border-t border-ink-700 pt-3">
            <SectionLabel className="mb-2">Suggested</SectionLabel>
            <div className="flex flex-col gap-1.5">
              {suggestedQuestions.slice(0, 2).map((q) => (
                <button
                  key={q}
                  onClick={() => onPick(q)}
                  className="group flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-[12px] text-muted transition-colors hover:bg-ink-800 hover:text-paper-dim"
                >
                  <span className="line-clamp-1">{q}</span>
                  <ArrowUpRight size={12} className="flex-shrink-0 text-ghost group-hover:text-brass" />
                </button>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
