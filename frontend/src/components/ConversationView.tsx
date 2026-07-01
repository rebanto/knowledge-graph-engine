import type { ConversationDetail } from "../types";
import { AnswerView } from "./AnswerView";
import { DeepResearchReport } from "./DeepResearchReport";
import { ErrorBoundary } from "./ErrorBoundary";

/**
 * Renders a conversation as a vertical thread of turns. Each turn reuses
 * AnswerView so a turn looks identical whether it just streamed in or was
 * rehydrated from history. Turns after the first are marked as follow-ups and
 * separated by a hairline rule, so the back-and-forth reads as one continuous
 * thread rather than a stack of unrelated answers. Each turn is wrapped in its
 * own ErrorBoundary so one malformed turn can't blank the whole thread.
 */
export function ConversationView({ conversation }: { conversation: ConversationDetail }) {
  return (
    <div className="flex flex-col">
      {conversation.turns.map((turn, i) => (
        <div key={turn.id}>
          {i > 0 && (
            <div className="my-9 flex items-center gap-3">
              <span className="h-px flex-1 bg-ink-700/50" />
              <span className="eyebrow text-faint">Follow-up</span>
              <span className="h-px flex-1 bg-ink-700/50" />
            </div>
          )}
          <ErrorBoundary>
            {turn.retrieval_type === "deep_research" ? (
              <DeepResearchReport report={turn} />
            ) : (
              <AnswerView report={turn} />
            )}
          </ErrorBoundary>
        </div>
      ))}
    </div>
  );
}
