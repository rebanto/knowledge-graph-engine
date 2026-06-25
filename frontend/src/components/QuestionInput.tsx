import { useState } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  loading: boolean;
}

export function QuestionInput({ onSubmit, loading }: QuestionInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || loading) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit} className="relative w-full">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask the graph a hard question…"
        disabled={loading}
        className="w-full rounded-xl border border-ink-700 bg-ink-800/70 px-4 py-3.5 pr-12 text-[14px] text-paper placeholder:text-faint outline-none transition-colors focus:border-brass/45 focus:bg-ink-800 disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className="absolute right-2.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg bg-brass text-ink-900 transition-colors disabled:opacity-30 enabled:hover:bg-brass-bright"
      >
        {loading ? <Loader2 size={15} className="animate-spin" /> : <ArrowUp size={15} strokeWidth={2.5} />}
      </button>
    </form>
  );
}
