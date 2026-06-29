import { ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import type { TrustScore } from "../types";

/**
 * Surfaces the faithfulness judge's verdict as a trust pill. This is the
 * measured form of "every fact traces to the sources": an independent LLM judge
 * checked each claim in the answer against the retrieved data, and `score` is the
 * fraction it found supported. No other research tool shows this to the user.
 */
export function TrustBadge({ trust, size = "md" }: { trust: TrustScore; size?: "sm" | "md" }) {
  const { score, supported, total } = trust;

  // No checkable claims → vacuously grounded; don't fake a percentage.
  if (score === null) {
    return (
      <span className={pill("text-faint bg-ink-800/70 border-ink-700", size)}
        title="The answer made no checkable factual claims to verify.">
        <ShieldQuestion size={icon(size)} strokeWidth={2.25} />
        grounding n/a
      </span>
    );
  }

  const pct = Math.round(score * 100);
  const tone =
    pct >= 90 ? "text-graph bg-graph-dim border-graph/30"
    : pct >= 70 ? "text-hybrid bg-hybrid-dim border-hybrid/30"
    : "text-flag bg-flag/10 border-flag/30";
  const Icon = pct >= 90 ? ShieldCheck : pct >= 70 ? ShieldCheck : ShieldAlert;

  return (
    <span
      className={pill(tone, size)}
      title={`An independent judge found ${supported} of ${total} claims supported by the retrieved data.`}
    >
      <Icon size={icon(size)} strokeWidth={2.25} />
      {pct}% grounded
      <span className="opacity-60 font-mono">{supported}/{total}</span>
    </span>
  );
}

function pill(tone: string, size: "sm" | "md") {
  const pad = size === "sm" ? "px-2 py-0.5 text-[10.5px]" : "px-2.5 py-1 text-[11px]";
  return `inline-flex items-center gap-1.5 rounded-full border font-medium ${pad} ${tone}`;
}

function icon(size: "sm" | "md") {
  return size === "sm" ? 11 : 12;
}
