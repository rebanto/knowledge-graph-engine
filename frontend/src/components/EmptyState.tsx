import { Database, Loader2, Sparkles, ArrowUpRight } from "lucide-react";

interface EmptyStateProps {
  onPick: (q: string) => void;
  hasSources: boolean;
  hasDescription: boolean;
  onGoToSources: () => void;
  onDiscover: () => void;
  discovering: boolean;
}

// The "no sources yet" state — shown in place of the example prompts.
export function NeedsSources({
  hasDescription,
  onGoToSources,
  onDiscover,
  discovering,
}: Pick<EmptyStateProps, "hasDescription" | "onGoToSources" | "onDiscover" | "discovering">) {
  return (
    <div className="animate-rise-in mt-6 flex flex-col items-center text-center">
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl border border-ink-700 bg-ink-800 glow-brass-soft">
        <Database size={20} className="text-brass/70" />
      </div>
      <p className="max-w-md text-[13.5px] leading-relaxed text-muted">
        This workspace has no sources yet. Point it at a few — papers, feeds, PDFs, web pages —
        and once they're read in you can trace how everything they mention connects.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
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
            className="flex items-center gap-2 rounded-lg bg-brass px-4 py-2 text-[13px] font-medium text-ink-900 transition-colors hover:bg-brass-bright hover:glow-brass-soft disabled:opacity-50"
          >
            {discovering ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {discovering ? "Looking…" : "Suggest some for me"}
          </button>
        )}
      </div>
    </div>
  );
}

// The example-prompt list shown under the hero when sources exist.
export function ExamplePrompts({
  onPick,
  questions,
  loading,
}: Pick<EmptyStateProps, "onPick"> & { questions?: string[]; loading?: boolean }) {
  const hasQuestions = questions && questions.length > 0;

  // Nothing to show and not loading — render nothing rather than fallback noise.
  if (!loading && !hasQuestions) return null;

  return (
    <div className="mt-8 w-full">
      <p className="eyebrow mb-3 text-center text-faint">Or start with one of these</p>
      <div className="flex flex-col gap-2">
        {loading && !hasQuestions ? (
          [0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-[42px] animate-pulse rounded-xl border border-ink-700 bg-ink-800/40"
              style={{ animationDelay: `${i * 80}ms` }}
            />
          ))
        ) : (
          <div className="animate-rise-in-stagger flex flex-col gap-2">
            {questions!.map((q) => (
              <button
                key={q}
                onClick={() => onPick(q)}
                className="group flex items-center justify-between gap-3 rounded-xl border border-ink-700 bg-ink-800/40 px-4 py-3 text-left text-[13px] text-paper-dim transition-all duration-200 ease-spring hover:border-brass/30 hover:bg-ink-800 hover:text-paper"
              >
                {q}
                <ArrowUpRight size={15} className="flex-shrink-0 text-ghost transition-colors group-hover:text-brass" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
