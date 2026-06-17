import { useEffect, useState } from "react";
import axios from "axios";
import { Network, MessageSquare, Database } from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { QuestionInput } from "./components/QuestionInput";
import { AnswerView } from "./components/AnswerView";
import { EmptyState } from "./components/EmptyState";
import { GraphViewer } from "./components/GraphViewer";
import { SourceManager } from "./components/SourceManager";
import {
  askQuestion, listReports, getReport, listWorkspaces, createWorkspace,
  listSources, discoverSources,
} from "./api";
import type { QuestionResponse, ReportSummary, Workspace } from "./types";

type Tab = "ask" | "explore" | "sources";

function describeError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.response?.data?.detail) return err.response.data.detail;
    if (!err.response) return "Couldn't connect to the server. Is the backend running?";
    return `Request failed (${err.response.status}).`;
  }
  return "Something went wrong.";
}

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("arxiv_seed");
  const [tab, setTab] = useState<Tab>("ask");
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [active, setActive] = useState<QuestionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);
  const [discovering, setDiscovering] = useState(false);

  useEffect(() => {
    listWorkspaces().then(setWorkspaces).catch(() => {});
  }, []);

  useEffect(() => {
    setActive(null);
    setSourceCount(null);
    listReports(workspaceId).then(setReports).catch(() => {});
    listSources(workspaceId).then((s) => setSourceCount(s.length)).catch(() => setSourceCount(0));
  }, [workspaceId]);

  const activeWorkspace = workspaces.find((w) => w.id === workspaceId) ?? null;
  const hasSources = sourceCount === null ? true : sourceCount > 0;

  async function handleSubmit(question: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await askQuestion(question, workspaceId);
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

  async function handleCreateWorkspace(
    name: string,
    domain: string,
    description: string,
    autoDiscover: boolean,
  ) {
    const workspace = await createWorkspace(name, domain, description || undefined);
    setWorkspaces((prev) => [...prev, workspace]);
    setWorkspaceId(workspace.id);
    setSourceCount(0);

    if (autoDiscover && description) {
      setDiscovering(true);
      try {
        const sources = await discoverSources(workspace.id);
        setSourceCount(sources.length);
        if (sources.length > 0) setTab("sources");
      } catch {
        // Discovery failed silently — user can retry from the empty state
      } finally {
        setDiscovering(false);
      }
    }
  }

  async function handleDiscover() {
    setDiscovering(true);
    setError(null);
    try {
      const sources = await discoverSources(workspaceId);
      setSourceCount((prev) => (prev ?? 0) + sources.length);
      if (sources.length > 0) setTab("sources");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setDiscovering(false);
    }
  }

  return (
    <div className="flex h-screen bg-[#0a0a0c]">
      <Sidebar
        reports={reports}
        activeId={active?.id ?? null}
        onSelect={(r) => { setTab("ask"); handleSelect(r); }}
        onNew={() => { setTab("ask"); setActive(null); }}
        workspaces={workspaces}
        workspaceId={workspaceId}
        onWorkspaceChange={setWorkspaceId}
        onCreateWorkspace={handleCreateWorkspace}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-1 border-b border-zinc-800/60 px-8 pt-3">
          {([
            { id: "ask"     as const, label: "Ask",     icon: MessageSquare },
            { id: "explore" as const, label: "Graph",   icon: Network },
            { id: "sources" as const, label: "Sources", icon: Database },
          ]).map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 rounded-t-md border-b-2 px-3 py-2 text-[12.5px] font-medium transition-colors ${
                tab === t.id
                  ? "border-zinc-100 text-zinc-100"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <t.icon size={13} />
              {t.label}
            </button>
          ))}
        </div>

        {tab === "ask" ? (
          <>
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
                <EmptyState
                  onPick={handleSubmit}
                  hasSources={hasSources}
                  hasDescription={!!activeWorkspace?.description}
                  onGoToSources={() => setTab("sources")}
                  onDiscover={handleDiscover}
                  discovering={discovering}
                />
              )}
            </div>
          </>
        ) : tab === "explore" ? (
          <div className="min-w-0 flex-1">
            <GraphViewer workspaceId={workspaceId} />
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            <SourceManager workspaceId={workspaceId} />
          </div>
        )}
      </main>
    </div>
  );
}
