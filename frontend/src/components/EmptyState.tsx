import { Database, Loader2, Sparkle, ArrowUpRight } from "lucide-react";

const EXAMPLES = [
  "Which authors have written the most papers in this dataset?",
  "What concepts cluster most tightly around reinforcement learning?",
  "What has Yijun Chen worked on, and how does it connect to everything else?",
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
      <div className="dot-grid flex flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl border border-ink-700 bg-ink-800">
          <Database size={20} className="text-faint" />
        </div>
        <h2 className="font-display text-[22px] font-medium text-paper">An empty graph</h2>
        <p className="mt-2.5 max-w-sm text-[13px] leading-relaxed text-muted">
          Point this workspace at a few sources — papers, feeds, PDFs, web pages.
          Once they're read in, you can trace the relationships between everything
          they mention and pull evidence straight from the text.
        </p>
        <div className="mt-7 flex flex-wrap justify-center gap-2">
          <button
            onClick={onGoToSources}
            className="rounded-lg border border-ink-600 bg-ink-800 px-4 py-2 text-[13px] font-medium text-paper-dim transition-colors hover:border-ink-500 hover:text-paper"
          >
            Add sources
          </button>
          {hasDescription && (
            <button
              onClick={onDiscover}
              disabled={discovering}
              className="flex items-center gap-2 rounded-lg bg-brass px-4 py-2 text-[13px] font-medium text-ink-900 transition-colors hover:bg-brass-bright disabled:opacity-50"
            >
              {discovering
                ? <Loader2 size={13} className="animate-spin" />
                : <Sparkle size={13} />}
              {discovering ? "Looking…" : "Suggest some for me"}
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="dot-grid flex flex-1 flex-col items-center justify-center px-6 text-center">
      <h2 className="font-display text-[22px] font-medium text-paper">What do you want to know?</h2>
      <p className="eyebrow mt-5 mb-3 text-faint">Or start with one of these</p>
      <div className="flex max-w-md flex-col gap-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="group flex items-center justify-between gap-3 rounded-lg border border-ink-700 bg-ink-800/50 px-4 py-2.5 text-left text-[12.5px] text-paper-dim transition-colors hover:border-brass/30 hover:bg-ink-800 hover:text-paper"
          >
            {q}
            <ArrowUpRight size={14} className="flex-shrink-0 text-ghost transition-colors group-hover:text-brass" />
          </button>
        ))}
      </div>
    </div>
  );
}
