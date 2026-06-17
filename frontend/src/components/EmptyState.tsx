import { Database, Loader2, Zap } from "lucide-react";

const EXAMPLES = [
  "Which authors have written the most papers in this dataset?",
  "What concepts are most commonly associated with reinforcement learning?",
  "What has Yijun Chen worked on, and what topics does it relate to?",
];

interface EmptyStateProps {
  onPick: (q: string) => void;
  hasSources: boolean;
  hasDescription: boolean;
  onGoToSources: () => void;
  onDiscover: () => void;
  discovering: boolean;
}

export function EmptyState({
  onPick,
  hasSources,
  hasDescription,
  onGoToSources,
  onDiscover,
  discovering,
}: EmptyStateProps) {
  if (!hasSources) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-900 ring-1 ring-zinc-800">
          <Database size={20} className="text-zinc-500" />
        </div>
        <h2 className="text-[16px] font-semibold text-zinc-200">No sources in this workspace</h2>
        <p className="mt-2 max-w-xs text-[13px] leading-relaxed text-zinc-500">
          Add sources to start building the knowledge graph. Once ingested, you can query relationships and retrieve evidence from the documents.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={onGoToSources}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-[13px] font-medium text-zinc-300 transition-colors hover:border-zinc-600 hover:text-zinc-100"
          >
            Add sources
          </button>
          {hasDescription && (
            <button
              onClick={onDiscover}
              disabled={discovering}
              className="flex items-center gap-2 rounded-lg bg-zinc-100 px-4 py-2 text-[13px] font-medium text-zinc-900 transition-colors hover:bg-white disabled:opacity-50"
            >
              {discovering
                ? <Loader2 size={13} className="animate-spin" />
                : <Zap size={13} />}
              {discovering ? "Discovering…" : "Auto-discover sources"}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
      <p className="mb-4 text-[12px] font-medium uppercase tracking-wider text-zinc-600">
        Try a query
      </p>
      <div className="flex flex-col gap-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-lg border border-zinc-800 bg-zinc-900/30 px-3.5 py-2 text-left text-[12.5px] text-zinc-400 transition-colors hover:border-zinc-700 hover:text-zinc-200"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
