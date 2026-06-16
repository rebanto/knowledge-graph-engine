import { useEffect, useState } from "react";
import axios from "axios";
import { Sidebar } from "./components/Sidebar";
import { QuestionInput } from "./components/QuestionInput";
import { AnswerView } from "./components/AnswerView";
import { EmptyState } from "./components/EmptyState";
import { askQuestion, listReports, getReport } from "./api";
import type { QuestionResponse, ReportSummary } from "./types";

function describeError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.response?.data?.detail) return err.response.data.detail;
    if (!err.response) return "Couldn't reach the knowledge graph engine. Is the backend running?";
    return `Request failed (${err.response.status}).`;
  }
  return "Something went wrong.";
}

export default function App() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [active, setActive] = useState<QuestionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listReports().then(setReports).catch(() => {});
  }, []);

  async function handleSubmit(question: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await askQuestion(question);
      setActive(result);
      setReports((prev) => [
        {
          id: result.id,
          question: result.question,
          answer: result.answer,
          retrieval_type: result.retrieval_type,
          version: result.version,
          created_at: result.created_at,
        },
        ...prev,
      ]);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(report: ReportSummary) {
    try {
      const full = await getReport(report.id);
      setActive(full);
    } catch {
      setError("Couldn't load that report.");
    }
  }

  return (
    <div className="flex h-screen bg-[#0a0a0c]">
      <Sidebar
        reports={reports}
        activeId={active?.id ?? null}
        onSelect={handleSelect}
        onNew={() => setActive(null)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-zinc-800/60 px-8 py-4">
          <div className="mx-auto max-w-2xl">
            <QuestionInput onSubmit={handleSubmit} loading={loading} />
            {error && <p className="mt-2 text-[12.5px] text-rose-400/80">{error}</p>}
          </div>
        </div>

        <div className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">
          {active ? (
            <div className="mx-auto max-w-2xl px-8 py-8">
              <AnswerView report={active} />
            </div>
          ) : (
            <EmptyState onPick={handleSubmit} />
          )}
        </div>
      </main>
    </div>
  );
}
