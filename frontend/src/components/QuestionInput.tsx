import { useState } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  loading: boolean;
  hero?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
}

export function QuestionInput({
  onSubmit,
  loading,
  hero = false,
  autoFocus = false,
  placeholder = "Ask a question...",
}: QuestionInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || loading) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit} className="group relative w-full">
      {/* illuminated focus halo - driven by CSS :focus-within, not state */}
      <div className="pointer-events-none absolute -inset-px rounded-xl opacity-0 transition-opacity duration-300 group-focus-within:opacity-100 glow-brass" />
      <input
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        disabled={loading}
        className={`relative w-full rounded-xl border border-ink-700 bg-ink-800/70 text-paper placeholder:text-faint outline-none transition-colors duration-200 ease-spring focus:border-brass/45 focus:bg-ink-800 disabled:opacity-60 ${
          hero
            ? "px-5 py-5 pr-14 text-[16px] leading-snug"
            : "px-4 py-3.5 pr-12 text-[14px]"
        }`}
      />
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className={`absolute top-1/2 flex -translate-y-1/2 items-center justify-center rounded-lg bg-brass text-ink-900 transition-colors duration-200 ease-spring disabled:opacity-30 enabled:hover:bg-brass-bright ${
          hero ? "right-3.5 h-10 w-10" : "right-2.5 h-8 w-8"
        }`}
      >
        {loading ? (
          <Loader2 size={hero ? 18 : 15} className="animate-spin" />
        ) : (
          <ArrowUp size={hero ? 18 : 15} strokeWidth={2.5} />
        )}
      </button>
    </form>
  );
}
