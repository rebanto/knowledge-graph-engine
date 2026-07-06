import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";

// ── URL state helpers ────────────────────────────────────────────────────────
const VALID_TABS = ["ask", "explore", "sources", "connect"] as const;

function readUrl() {
  const p = new URLSearchParams(window.location.search);
  const w = p.get("w") ?? "arxiv_seed";
  const rawT = p.get("t") ?? "";
  const t: import("./components/Rail").Tab = (VALID_TABS as readonly string[]).includes(rawT)
    ? (rawT as import("./components/Rail").Tab)
    : "ask";
  const c = p.get("c") ?? null;
  return { w, t, c };
}

function writeUrl(workspaceId: string, tab: string, conversationId: string | null) {
  const p = new URLSearchParams();
  p.set("w", workspaceId);
  p.set("t", tab);
  if (conversationId) p.set("c", conversationId);
  history.replaceState(null, "", `?${p}`);
}
import axios from "axios";
import { Loader2, ArrowRight, Sparkles, Plus } from "lucide-react";
import { Rail, type Tab } from "./components/Rail";
import { AuthProvider, useAuth } from "./auth";
import { Button } from "./components/ui";
import { LoginScreen } from "./components/LoginScreen";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { QuestionInput } from "./components/QuestionInput";
import { ConversationView } from "./components/ConversationView";
import { DeepResearchPanel } from "./components/DeepResearchPanel";
import { NeedsSources } from "./components/EmptyState";
import { ResearchGaps } from "./components/ResearchGaps";
import { SourceManager } from "./components/SourceManager";
import { ConnectPanel } from "./components/ConnectPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { WorkspacePulse, type SourceStats } from "./components/WorkspacePulse";
import {
  streamQuestion, listConversations, getConversation, deleteConversation,
  listWorkspaces, createWorkspace, updateWorkspace, deleteWorkspace,
  listSources, discoverSources, getSuggestedQuestions,
} from "./api";
import type { ConversationSummary, ConversationDetail, ResearchGap, Source, Workspace } from "./types";

// Code-split the D3 graph view: it's the heaviest dependency in the bundle and
// only needed when the user opens the Explore tab.
const GraphViewer = lazy(() =>
  import("./components/GraphViewer").then((m) => ({ default: m.GraphViewer })),
);

function describeError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.response?.data?.detail) return err.response.data.detail;
    if (!err.response) return "Couldn't connect to the server. Is the backend running?";
    return `Request failed (${err.response.status}).`;
  }
  return "Something went wrong.";
}

function buildSourceStats(sources: Source[]): SourceStats {
  return {
    total: sources.length,
    ready: sources.filter((s) => s.status === "success").length,
    active: sources.filter((s) => s.status === "pending" || s.status === "running").length,
    error: sources.filter((s) => s.status === "error").length,
    arxiv: sources.filter((s) => s.type === "arxiv_feed").length,
    rss: sources.filter((s) => s.type === "rss").length,
    web: sources.filter((s) => s.type === "web_url").length,
    pdf: sources.filter((s) => s.type === "pdf_upload").length,
  };
}

function AppContent() {
  // Read once on mount; lazy useState (not a ref) so render never reads a ref.
  const [initialUrl] = useState(readUrl);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState(initialUrl.w);
  const [tab, setTab] = useState<Tab>(initialUrl.t);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConvo, setActiveConvo] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [submittedQuestion, setSubmittedQuestion] = useState<string | null>(null);
  // Deep Research mode: when on, a submitted question runs the multi-agent
  // orchestrator (plan → sub-agents → synthesize → verify) instead of the
  // single-shot pipeline. `deepQuestion` holds the active run's question.
  const [deepMode, setDeepMode] = useState(false);
  const [deepQuestion, setDeepQuestion] = useState<string | null>(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  // The standalone question a follow-up was condensed into, shown live while the
  // turn streams so the user sees how their "what about...?" was interpreted.
  const [rewriteNote, setRewriteNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);
  const [sourceStats, setSourceStats] = useState<SourceStats | null>(null);
  const [processingCount, setProcessingCount] = useState(0);
  const [discovering, setDiscovering] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [selectedGap, setSelectedGap] = useState<ResearchGap | null>(null);
  const [hoverGap, setHoverGap] = useState<ResearchGap | null>(null);
  const cancelStreamRef = useRef<(() => void) | null>(null);
  const sourcePollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Pending conversation ID from the URL - opened once the list arrives.
  const pendingConvoId = useRef<string | null>(initialUrl.c);

  useEffect(() => {
    listWorkspaces()
      .then(setWorkspaces)
      .catch((err) => setError(describeError(err)));
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations(workspaceId));
    } catch (err) {
      setError(describeError(err));
    }
  }, [workspaceId]);

  const refreshSources = useCallback(async () => {
    try {
      const sources = await listSources(workspaceId);
      setSourceCount(sources.length);
      setSourceStats(buildSourceStats(sources));
      setProcessingCount(
        sources.filter((s) => s.status === "pending" || s.status === "running").length,
      );
    } catch {
      setSourceCount(0);
      setSourceStats(null);
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

  // Reset per-workspace view state the moment the workspace switches - done
  // during render (the documented "adjusting state when props change" pattern)
  // so the old workspace's data never paints against the new one.
  const [prevWorkspaceId, setPrevWorkspaceId] = useState(workspaceId);
  if (prevWorkspaceId !== workspaceId) {
    setPrevWorkspaceId(workspaceId);
    setActiveConvo(null);
    setDeepQuestion(null);
    setLoading(false);
    setSubmittedQuestion(null);
    setDeepLoading(false);
    setSourceCount(null);
    setSourceStats(null);
    setProcessingCount(0);
    setSuggestedQuestions([]);
    setSelectedGap(null);
    setHoverGap(null);
  }

  useEffect(() => {
    // False positive: these async helpers only set state after their awaits
    // resolve (network round-trip), never synchronously in the effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refreshConversations();
    refreshSources();
    getSuggestedQuestions(workspaceId)
      .then(setSuggestedQuestions)
      .catch(() => setSuggestedQuestions([]));
  }, [workspaceId, refreshConversations, refreshSources]);

  // Cancel in-flight stream when component unmounts
  useEffect(() => () => { cancelStreamRef.current?.(); }, []);

  // Keep the URL in sync so refresh restores exactly this view.
  useEffect(() => {
    writeUrl(workspaceId, tab, activeConvo?.id ?? null);
  }, [workspaceId, tab, activeConvo?.id]);

  // If the page loaded with ?c=<id>, open that conversation once the list is in.
  useEffect(() => {
    const cid = pendingConvoId.current;
    if (!cid || conversations.length === 0) return;
    pendingConvoId.current = null;
    if (!conversations.find((c) => c.id === cid)) return;
    getConversation(cid)
      .then(setActiveConvo)
      .catch(() => {});
  }, [conversations]);

  // If the URL named a workspace that doesn't exist, fall back to the first one
  // (render-time state adjustment - no effect round-trip).
  if (workspaces.length > 0 && !workspaces.some((w) => w.id === workspaceId)) {
    setWorkspaceId(workspaces[0].id);
  }

  const activeWorkspace = workspaces.find((w) => w.id === workspaceId) ?? null;
  const hasSources = sourceCount === null ? true : sourceCount > 0;

  // The single "back to a blank question" action, reused by the rail's New
  // button and the inline new-thread buttons. Always lands on a fresh Ask view.
  function handleNewThread() {
    cancelStreamRef.current?.();
    setTab("ask");
    setDeepQuestion(null);
    setLoading(false);
    setSubmittedQuestion(null);
    setDeepLoading(false);
    setActiveConvo(null);
    setError(null);
    setStreamStatus(null);
    setRewriteNote(null);
  }

  function handleSubmit(question: string) {
    // Cancel any in-flight stream from a previous question
    cancelStreamRef.current?.();
    setSubmittedQuestion(question);

    // Deep Research is a standalone run (not a conversation turn): hand the
    // question to the orchestrator panel, which owns its own SSE stream.
    if (deepMode && !activeConvo) {
      setError(null);
      setDeepQuestion(question);
      setDeepLoading(true);
      return;
    }

    const conversationId = activeConvo?.id ?? null;
    setLoading(true);
    setError(null);
    setRewriteNote(null);
    setStreamStatus(conversationId ? "Reading the thread..." : "Choosing where to look...");

    const cancel = streamQuestion(
      question,
      workspaceId,
      {
        onProgress: (status) => setStreamStatus(status),
        onRouting: () => {},
        onRewrite: (standalone) => setRewriteNote(standalone),
        onDone: (result) => {
          setStreamStatus(null);
          setRewriteNote(null);
          setLoading(false);
          setSubmittedQuestion(null);
          setActiveConvo((prev) => {
            // Append to the open thread when the turn belongs to it...
            if (prev && result.conversation_id && result.conversation_id === prev.id) {
              return { ...prev, turns: [...prev.turns, result], updated_at: result.created_at };
            }
            // ...otherwise this opened a brand-new conversation.
            return {
              id: result.conversation_id ?? result.id,
              workspace_id: workspaceId,
              title: result.question,
              created_at: result.created_at,
              updated_at: result.created_at,
              turns: [result],
            };
          });
          refreshConversations();
        },
        onError: (detail) => {
          setError(detail);
          setStreamStatus(null);
          setRewriteNote(null);
          setLoading(false);
          setSubmittedQuestion(null);
        },
      },
      conversationId,
    );

    cancelStreamRef.current = cancel;
  }

  async function handleSelectConversation(conversation: ConversationSummary) {
    try {
      const full = await getConversation(conversation.id);
      setActiveConvo(full);
    } catch {
      setError("Couldn't load that conversation.");
    }
  }

  const handleDeepSaved = useCallback(async (conversationId: string) => {
    try {
      const full = await getConversation(conversationId);
      setActiveConvo(full);
      setDeepQuestion(null);
      setSubmittedQuestion(null);
      setDeepLoading(false);
      setTab("ask");
      setError(null);
      await refreshConversations();
    } catch {
      setError("Deep Research finished, but the saved conversation couldn't be opened.");
      setSubmittedQuestion(null);
      setDeepLoading(false);
      await refreshConversations();
    }
  }, [refreshConversations]);

  const handleDeepSettled = useCallback(() => {
    setSubmittedQuestion(null);
    setDeepLoading(false);
  }, []);

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
    setSourceStats(buildSourceStats([]));

    if (autoDiscover && description) {
      setDiscovering(true);
      try {
        const sources = await discoverSources(workspace.id);
        setSourceCount(sources.length);
        setSourceStats(buildSourceStats(sources));
        if (sources.length > 0) setTab("sources");
      } catch {
        // Discovery failed - user can retry from the empty state
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
      setConversations([]);
      setActiveConvo(null);
    }
  }

  async function handleDeleteConversation(conversationId: string) {
    await deleteConversation(conversationId);
    setConversations((prev) => prev.filter((c) => c.id !== conversationId));
    if (activeConvo?.id === conversationId) setActiveConvo(null);
  }

  async function handleDiscover() {
    setDiscovering(true);
    setError(null);
    try {
      const sources = await discoverSources(workspaceId);
      await refreshSources();
      if (sources.length > 0) setTab("sources");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setDiscovering(false);
    }
  }

  // Status / banners shown beneath the ask input in both hero and answered states.
  const askStatus = (
    <>
      {streamStatus && (
        <p className="mt-2.5 flex items-center gap-1.5 text-[12px] text-brass/80">
          <Loader2 size={11} className="animate-spin flex-shrink-0" />
          {streamStatus}
        </p>
      )}
      {rewriteNote && (
        <p className="mt-1 text-[12px] italic text-faint">interpreted as: “{rewriteNote}”</p>
      )}
      {error && <p className="mt-2.5 text-[12.5px] text-flag">{error}</p>}
      {processingCount > 0 && !loading && (
        <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-brass/20 bg-brass-dim px-3 py-2">
          <div className="flex items-center gap-2 text-[12px] text-brass/90">
            <Loader2 size={11} className="animate-spin flex-shrink-0" />
            <span>
              {processingCount === 1
                ? "1 source is still being read in"
                : `${processingCount} sources are still being read in`}
              {" Content is still indexing."}
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
    </>
  );

  // Mode toggle: flip a question between the single-shot pipeline and the
  // multi-agent Deep Research orchestrator. Reused in the hero and the deep view.
  const deepToggle = (
    <button
      type="button"
      onClick={() => setDeepMode((v) => !v)}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors duration-200 ${
        deepMode
          ? "border-brass/40 bg-brass-dim text-brass glow-brass-soft"
          : "border-ink-700 text-faint hover:text-paper-dim"
      }`}
      title="Break the question into subquestions, research them, then verify the answer."
    >
      <Sparkles size={13} strokeWidth={2.25} />
      Deep Research
      <span className={`ml-0.5 h-1.5 w-1.5 rounded-full ${deepMode ? "bg-brass" : "bg-ink-700"}`} />
    </button>
  );

  return (
    <div className="relative flex h-screen overflow-hidden text-paper">
      <div className="app-aura" />
      <div className="app-vignette" />

      <Rail
        tab={tab}
        onTab={(t) => setTab(t)}
        onNewThread={handleNewThread}
        historyOpen={historyOpen}
        onToggleHistory={() => setHistoryOpen((o) => !o)}
        historyCount={conversations.length}
        workspace={activeWorkspace}
      />

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        conversations={conversations}
        activeId={activeConvo?.id ?? null}
        onSelect={(c) => { setTab("ask"); setDeepQuestion(null); handleSelectConversation(c); }}
        onNew={handleNewThread}
        onDeleteConversation={handleDeleteConversation}
        workspaces={workspaces}
        workspaceId={workspaceId}
        onWorkspaceChange={setWorkspaceId}
        onCreateWorkspace={handleCreateWorkspace}
        onUpdateWorkspace={handleUpdateWorkspace}
        onDeleteWorkspace={handleDeleteWorkspace}
      />

      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        {tab === "ask" ? (
          activeConvo ? (
            // ── In a thread: slim follow-up bar pinned on top, turns below ──────
            <>
              <div className="border-b border-ink-700/60 px-8 py-3.5">
                <div className="mx-auto max-w-2xl">
                  <div className="mb-2.5 flex items-center justify-between gap-3">
                    <p className="min-w-0 truncate font-display text-[14px] text-paper-dim" title={activeConvo.title}>
                      {activeConvo.title}
                    </p>
                    <Button variant="outline" size="sm" onClick={handleNewThread} className="flex-shrink-0">
                      <Plus size={13} />
                      New thread
                    </Button>
                  </div>
                  <QuestionInput
                    onSubmit={handleSubmit}
                    loading={loading}
                    submittedQuestion={submittedQuestion}
                    placeholder="Ask a follow-up..."
                  />
                  {askStatus}
                </div>
              </div>
              <div className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">
                <div className="mx-auto max-w-2xl px-8 py-9">
                  <ConversationView conversation={activeConvo} />
                </div>
              </div>
            </>
          ) : deepQuestion ? (
            // ── Deep Research run: input bar on top, the agent trace below ──────
            <>
              <div className="border-b border-ink-700/60 px-8 py-3.5">
                <div className="mx-auto max-w-2xl">
                  <QuestionInput
                    onSubmit={handleSubmit}
                    loading={deepLoading}
                    submittedQuestion={submittedQuestion ?? deepQuestion}
                    placeholder="Ask another deep question..."
                  />
                  <div className="mt-2.5 flex items-center justify-between">
                    {deepToggle}
                    <Button variant="outline" size="sm" onClick={handleNewThread}>
                      <Plus size={13} />
                      New question
                    </Button>
                  </div>
                  {error && <p className="mt-2.5 text-[12.5px] text-flag">{error}</p>}
                </div>
              </div>
              <div className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">
                <div className="mx-auto max-w-2xl px-8 py-9">
                  <DeepResearchPanel
                    question={deepQuestion}
                    workspaceId={workspaceId}
                    onSaved={handleDeepSaved}
                    onSettled={handleDeepSettled}
                  />
                </div>
              </div>
            </>
          ) : (
            // ── Empty: a centred console, the question the centre of gravity ─
            <div className="dot-grid min-w-0 flex-1 overflow-y-auto scrollbar-thin">
              <div className="flex min-h-full flex-col items-center justify-center px-6 py-16">
                <div className="animate-rise-in w-full max-w-4xl">
                  <h1 className="text-glow mb-7 text-center font-display text-[34px] font-medium leading-[1.1] tracking-tight text-paper">
                    What do you want to know?
                  </h1>
                  <QuestionInput
                    onSubmit={handleSubmit}
                    loading={loading}
                    submittedQuestion={submittedQuestion}
                    hero
                    autoFocus
                  />
                  {askStatus}

                  <div className="mt-3.5 flex justify-center">{deepToggle}</div>

                  {hasSources ? (
                    <WorkspacePulse
                      workspace={activeWorkspace}
                      stats={sourceStats}
                      conversations={conversations}
                      suggestedQuestions={suggestedQuestions}
                      onPick={handleSubmit}
                      onGoToSources={() => setTab("sources")}
                      onGoToGraph={() => setTab("explore")}
                    />
                  ) : (
                    <NeedsSources
                      hasDescription={!!activeWorkspace?.description}
                      onGoToSources={() => setTab("sources")}
                      onDiscover={handleDiscover}
                      discovering={discovering}
                    />
                  )}
                </div>
              </div>
            </div>
          )
        ) : tab === "explore" ? (
          <div className="flex min-w-0 flex-1">
            <ErrorBoundary>
              <ResearchGaps
                key={workspaceId}
                workspaceId={workspaceId}
                selectedGap={selectedGap}
                onSelectGap={setSelectedGap}
                onHoverGap={setHoverGap}
              />
              <Suspense fallback={<div className="flex flex-1 items-center justify-center text-[12px] text-muted">Loading graph view...</div>}>
                <GraphViewer workspaceId={workspaceId} gapFocus={selectedGap ?? hoverGap} />
              </Suspense>
            </ErrorBoundary>
          </div>
        ) : tab === "sources" ? (
          <div className="min-h-0 min-w-0 flex-1">
            <ErrorBoundary>
              <SourceManager workspaceId={workspaceId} />
            </ErrorBoundary>
          </div>
        ) : tab === "connect" ? (
          <div className="min-h-0 min-w-0 flex-1">
            <ErrorBoundary>
              <ConnectPanel workspaceId={workspaceId} workspaceName={activeWorkspace?.name ?? null} />
            </ErrorBoundary>
          </div>
        ) : null}
      </main>
    </div>
  );
}

function AuthGate() {
  const { status } = useAuth();
  if (status === "loading") {
    return (
      <div className="relative flex h-screen items-center justify-center overflow-hidden bg-ink-950 text-paper">
        <div className="app-aura" />
        <div className="app-vignette" />
        <div className="relative z-10 flex items-center gap-2 text-[13px] text-muted">
          <Loader2 size={14} className="animate-spin text-brass" />
          Loading
        </div>
      </div>
    );
  }
  if (status === "anonymous") return <LoginScreen />;
  return <AppContent />;
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
