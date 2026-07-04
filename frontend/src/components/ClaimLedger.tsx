import { AlertTriangle, CheckCircle, ClipboardCheck, ShieldQuestion } from "lucide-react";
import type { TrustScore } from "../types";
import { Card } from "./ui";

function fallbackClaims(trust: TrustScore) {
  if (trust.claims && trust.claims.length > 0) return trust.claims;
  return (trust.unsupported_claims ?? []).map((claim) => ({ claim, supported: false }));
}

export function ClaimLedger({ trust }: { trust: TrustScore }) {
  const claims = fallbackClaims(trust);
  const hasClaims = claims.length > 0;

  if (!hasClaims && trust.score === null) {
    return (
      <Card as="section" className="p-4">
        <div className="flex items-start gap-3">
          <ShieldQuestion size={16} className="mt-0.5 flex-shrink-0 text-faint" />
          <div>
            <p className="font-display text-[15px] font-medium text-paper">Claim ledger</p>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              No checkable claims were found, or verification was unavailable.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card as="section" className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ClipboardCheck size={15} className="text-brass" />
          <h2 className="font-display text-[15px] font-medium text-paper">Claim ledger</h2>
        </div>
        <p className="font-mono text-[11px] text-faint">
          {trust.supported}/{trust.total} supported
        </p>
      </div>

      <div className="grid gap-2">
        {claims.map((item, index) => (
          <div
            key={`${item.claim}-${index}`}
            className={`rounded-lg border px-3 py-2.5 ${
              item.supported
                ? "border-ok/20 bg-ok/5"
                : "border-flag/25 bg-flag/5"
            }`}
          >
            <div className="flex items-start gap-2">
              {item.supported ? (
                <CheckCircle size={13} className="mt-0.5 flex-shrink-0 text-ok" />
              ) : (
                <AlertTriangle size={13} className="mt-0.5 flex-shrink-0 text-flag" />
              )}
              <p className="text-[12px] leading-relaxed text-paper-dim">{item.claim}</p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
