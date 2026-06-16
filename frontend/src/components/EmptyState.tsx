const EXAMPLES = [
  "Which authors have written the most papers in this dataset?",
  "What concepts are most commonly associated with reinforcement learning?",
  "What has Yijun Chen worked on, and what topics does it relate to?",
];

export function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
      <h2 className="text-[22px] font-semibold tracking-tight text-zinc-100">
        Ask the graph something
      </h2>
      <p className="mt-2 max-w-sm text-[13.5px] leading-relaxed text-zinc-500">
        Questions are routed to graph traversal, semantic search, or both — answers are
        grounded in the ingested papers, never invented.
      </p>
      <div className="mt-6 flex flex-col gap-2">
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
