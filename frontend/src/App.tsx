import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { Network, MessageSquare, Database, Loader2, ArrowRight, Server } from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { QuestionInput } from "./components/QuestionInput";
import { AnswerView } from "./components/AnswerView";
import { EmptyState } from "./components/EmptyState";
import { GraphViewer } from "./components/GraphViewer";
import { SourceManager } from "./components/SourceManager";
import { CoordinatorDashboard } from "./components/CoordinatorDashboard";
import { ErrorBoundary } from "./components/ErrorBoundary";
import {
  streamQuestion, listReports, getReport, listWorkspaces, createWorkspace,
  updateWorkspace, deleteWorkspace, deleteReport,
  listSources, discoverSources,
} from "./api";
import type { QuestionResponse, ReportSummary, Workspace } from "./types";

type Tab = "ask" | "explore" | "sources" | "cluster";

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
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);
  const [processingCount, setProcessingCount] = useState(0);
  const [discovering, setDiscovering] = useState(false);
  const cancelStreamRef = useRef<(() => void) | null>(null);
  const sourcePollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    listWorkspaces()
      .then(setWorkspaces)
      .catch((err) => setError(describeError(err)));
  }, []);

  const refreshSources = useCallback(async () => {
    try {
      const sources = await listSources(workspaceId);
      setSourceCount(sources.length);
      setProcessingCount(
        sources.filter((s) => s.status === "pending" || s.status === "running").length,
      );
    } catch {
      setSourceCount(0);
      setProcessingCount(0);
    }
  }, [workspaceId]);

  // Poll source statuses while any are still ingesting so the banner auto-clears.
  useEffect(() => {
    if (sourcePollRef.current) { clearTimeout(sourcePollRef.current); sourcePollRef.current = null; }
    if (processingCount === 0) return;
    sourcePollRef.current = setTimeout(refreshSources, 4000);
    return () => { if (sourcePollRef.current) clearTimeout(sourcePollRef.current); };
  }, [processingCount, refreshSources]);

  useEffect(() => {
    setActive(null);
    setSourceCount(null);
    setProcessingCount(0);
    listReports(workspaceId)
      .then(setReports)
      .catch((err) => setError(describeError(err)));
    refreshSources();
  }, [workspaceId, refreshSources]);

  // Cancel in-flight stream when component unmounts
  useEffect(() => () => { cancelStreamRef.current?.(); }, []);

  const activeWorkspace = workspaces.find((w) => w.id === workspaceId) ?? null;
  const hasSources = sourceCount === null ? true : sourceCount > 0;

  function handleSubmit(question: string) {
    // Cancel any in-flight stream from a previous question
    cancelStreamRef.current?.();

    setLoading(true);
    setError(null);
    setStreamStatus("Analyzing question…");

    const cancel = streamQuestion(question, workspaceId, {
      onProgress: (status) => setStreamStatus(status),
      onRouting: () => {},
      onDone: (result) => {
        setActive(result);
        setStreamStatus(null);
        setLoading(false);
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
      },
      onError: (detail) => {
        setError(detail);
        setStreamStatus(null);
        setLoading(false);
      },
    });

    cancelStreamRef.current = cancel;
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
        // Discovery failed — user can retry from the empty state
      } finally {
        setDiscovering(false);
      }
    }
  }

  async function handleUpdateWorkspace(
    id: string,
    name: string,
    domain: string,
    description: string,
  ) {
    const updated = await updateWorkspace(id, { name, domain, description: description || undefined });
    setWorkspaces((prev) => prev.map((w) => (w.id === id ? updated : w)));
  }

  async function handleDeleteWorkspace(id: string) {
    await deleteWorkspace(id);
    setWorkspaces((prev) => {
      const remaining = prev.filter((w) => w.id !== id);
      if (workspaceId === id) {
        const next = remaining[0];
        if (next) setWorkspaceId(next.id);
      }
      return remaining;
    });
    if (workspaceId === id) {
      setReports([]);
      setActive(null);
    }
  }

  async function handleDeleteReport(reportId: string) {
    await deleteReport(reportId);
    setReports((prev) => prev.filter((r) => r.id !== reportId));
    if (active?.id === reportId) setActive(null);
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
    <div className="flex h-screen bg-ink-900 text-paper">
      <Sidebar
        reports={reports}
        activeId={active?.id ?? null}
        onSelect={(r) => { setTab("ask"); handleSelect(r); }}
        onNew={() => { setTab("ask"); setActive(null); }}
        onDeleteReport={handleDeleteReport}
        workspaces={workspaces}
        workspaceId={workspaceId}
        onWorkspaceChange={setWorkspaceId}
        onCreateWorkspace={handleCreateWorkspace}
        onUpdateWorkspace={handleUpdateWorkspace}
        onDeleteWorkspace={handleDeleteWorkspace}
      />

      <main className="flex min-w-0 flex-1 flex-col bg-ink-900">
        <div className="flex items-center gap-1 border-b border-ink-700 px-8 pt-3">
          {([
            { id: "ask"     as const, label: "Ask",     icon: MessageSquare },
            { id: "explore" as const, label: "Graph",   icon: Network },
            { id: "sources" as const, label: "Sources", icon: Database },
            { id: "cluster" as const, label: "Cluster", icon: Server },
          ]).map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-[12.5px] font-medium transition-colors ${
                tab === t.id
                  ? "border-brass text-paper"
                  : "border-transparent text-muted hover:text-paper-dim"
              }`}
            >
              <t.icon size={13} className={tab === t.id ? "text-brass" : ""} />
              {t.label}
            </button>
          ))}
        </div>

        {tab === "ask" ? (
          <>
            <div className="border-b border-ink-700 px-8 py-4">
              <div className="mx-auto max-w-2xl">
                <QuestionInput onSubmit={handleSubmit} loading={loading} />
                {streamStatus && (
                  <p className="mt-2 flex items-center gap-1.5 text-[12px] text-brass/80">
                    <Loader2 size={11} className="animate-spin flex-shrink-0" />
                    {streamStatus}
                  </p>
                )}
                {error && <p className="mt-2 text-[12.5px] text-flag">{error}</p>}
                {processingCount > 0 && !loading && (
                  <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-brass/20 bg-brass-dim px-3 py-2">
                    <div className="flex items-center gap-2 text-[12px] text-brass/90">
                      <Loader2 size={11} className="animate-spin flex-shrink-0" />
                      <span>
                        {processingCount === 1
                          ? "1 source is still being read in"
                          : `${processingCount} sources are still being read in`}
                        {" — their content isn't searchable yet"}
                      </span>
                    </div>
                    <button
                      onClick={() => setTab("sources")}
                      className="flex flex-shrink-0 items-center gap-1 text-[11.5px] text-brass/70 hover:text-brass-bright"
                    >
                      View <ArrowRight size={10} />
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">
              {active ? (
                <div className="mx-auto max-w-2xl px-8 py-8">
                  <ErrorBoundary>
                    <AnswerView report={active} />
                  </ErrorBoundary>
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
            <ErrorBoundary>
              <GraphViewer workspaceId={workspaceId} />
            </ErrorBoundary>
          </div>
        ) : tab === "sources" ? (
          <div className="min-w-0 flex-1">
            <ErrorBoundary>
              <SourceManager workspaceId={workspaceId} />
            </ErrorBoundary>
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            <ErrorBoundary>
              <CoordinatorDashboard />
            </ErrorBoundary>
          </div>
        )}
      </main>
    </div>
  );
}
