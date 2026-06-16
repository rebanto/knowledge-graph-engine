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
        placeholder="Ask about entities, relationships, or research findings…"
        disabled={loading}
        className="w-full rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3.5 pr-12 text-[14px] text-zinc-100 placeholder:text-zinc-500 outline-none transition-colors focus:border-zinc-600 disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className="absolute right-2.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg bg-zinc-100 text-zinc-900 transition-opacity disabled:opacity-30 enabled:hover:bg-white"
      >
        {loading ? <Loader2 size={15} className="animate-spin" /> : <ArrowUp size={15} />}
      </button>
    </form>
  );
}
