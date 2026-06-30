import { ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import type { TrustScore } from "../types";
import { Badge } from "./ui";

/**
 * Surfaces the faithfulness judge's verdict as a trust pill. This is the
 * measured form of "every fact traces to the sources": an independent LLM judge
 * checked each claim in the answer against the retrieved data, and `score` is the
 * fraction it found supported. No other research tool shows this to the user.
 */
export function TrustBadge({ trust, size = "md" }: { trust: TrustScore; size?: "sm" | "md" }) {
  const { score, supported, total } = trust;
  const iconSize = size === "sm" ? 11 : 12;

  // No checkable claims → vacuously grounded; don't fake a percentage.
  if (score === null) {
    return (
      <Badge tone="neutral" size={size} title="The answer made no checkable factual claims to verify.">
        <ShieldQuestion size={iconSize} strokeWidth={2.25} />
        grounding n/a
      </Badge>
    );
  }

  const pct = Math.round(score * 100);
  const tone = pct >= 90 ? "graph" : pct >= 70 ? "hybrid" : "flag";
  const Icon = pct >= 70 ? ShieldCheck : ShieldAlert;

  return (
    <Badge
      tone={tone}
      size={size}
      title={`An independent judge found ${supported} of ${total} claims supported by the retrieved data.`}
    >
      <Icon size={iconSize} strokeWidth={2.25} />
      {pct}% grounded
      <span className="font-mono opacity-60">{supported}/{total}</span>
    </Badge>
  );
}
