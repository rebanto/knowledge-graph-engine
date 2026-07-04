import { useCallback, useEffect, useState } from "react";
import {
  Plug, Copy, Check, Loader2, RefreshCw, ShieldAlert, Terminal,
  FolderOpen, ClipboardPaste, RotateCw, Search, Route, GitBranch,
  Users, ScrollText, Sparkles, KeyRound,
} from "lucide-react";
import { Card } from "./ui";
import { getMcpConfig } from "../api";
import type { McpConfig } from "../types";

const ABILITIES: { icon: typeof Search; title: string; body: string }[] = [
  { icon: Search, title: "Search your documents", body: "Pull the most relevant passages from your sources, with citations." },
  { icon: Route, title: "Trace connections", body: "Find how two things are linked, step by step, through your graph." },
  { icon: GitBranch, title: "Explore an entity", body: "Get everything known about one person, org, or idea and its links." },
  { icon: Users, title: "Weigh disagreements", body: "See where your sources contradict each other instead of guessing." },
  { icon: ScrollText, title: "Deep research", body: "Run the full multi-agent research pass and get a trust score back." },
];

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* Clipboard blocked; user can select manually. */
    }
  }, [text]);
  return (
    <button
      onClick={copy}
      className="inline-flex flex-shrink-0 items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-800/60 px-2.5 py-1.5 text-[11.5px] font-medium text-paper-dim transition-colors hover:border-brass/40 hover:text-brass"
    >
      {copied ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
      {copied ? "Copied" : label}
    </button>
  );
}

function Step({ n, icon: Icon, title, children }: {
  n: number; icon: typeof Search; title: string; children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3.5">
      <div className="flex flex-col items-center">
        <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-brass/30 bg-brass-dim font-display text-[13px] font-medium text-brass">
          {n}
        </span>
        <span className="mt-1 w-px flex-1 bg-ink-700/70" />
      </div>
      <div className="min-w-0 flex-1 pb-6">
        <div className="mb-2 flex items-center gap-2 text-[13.5px] font-medium text-paper">
          <Icon size={14} className="text-brass/80" />
          {title}
        </div>
        <div className="text-[12.5px] leading-relaxed text-muted">{children}</div>
      </div>
    </div>
  );
}

export function ConnectPanel(
  { workspaceId, workspaceName }: { workspaceId: string; workspaceName: string | null },
) {
  const [data, setData] = useState<McpConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [clientKey, setClientKey] = useState<string>("claude_desktop");

  // Reset during render so a previous workspace's config never paints against a new one.
  const [prevWs, setPrevWs] = useState(workspaceId);
  if (prevWs !== workspaceId) {
    setPrevWs(workspaceId);
    setData(null);
    setError(null);
    setLoading(true);
  }

  const fetchConfig = useCallback(async () => {
    try {
      setData(await getMcpConfig(workspaceId));
      setError(null);
    } catch {
      setError("Couldn't load the connection settings. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    // False positive: fetchConfig only sets state after its await resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchConfig();
  }, [fetchConfig]);

  function retry() {
    setLoading(true);
    fetchConfig();
  }

  const activeClient =
    data?.clients.find((c) => c.key === clientKey) ?? data?.clients[0];
  const configJson = activeClient ? JSON.stringify(activeClient.config, null, 2) : "";
  const displayWorkspaceName = workspaceName ?? data?.workspace_name ?? null;

  return (
    <div className="h-full min-w-0 overflow-y-auto scrollbar-thin">
      <div className="mx-auto max-w-2xl px-8 py-9">
        <div className="mb-6 flex items-start gap-3.5">
          <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border border-brass/25 bg-brass-dim">
            <Plug size={19} className="text-brass" />
          </div>
          <div className="min-w-0">
            <h1 className="font-display text-[22px] font-medium leading-tight text-paper">
              Use this as memory for your AI tools
            </h1>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
              Connect Claude Desktop, Claude Code, Cursor, Windsurf, VS Code, or any
              MCP-compatible assistant to this workspace. Instead of guessing, they can
              pull verified, connected facts straight from your sources, with citations.
            </p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-16 text-[13px] text-muted">
            <Loader2 size={14} className="animate-spin" /> Preparing your connection settings...
          </div>
        ) : error ? (
          <Card variant="flat" className="flex items-center justify-between gap-3 p-4">
            <p className="text-[12.5px] text-flag">{error}</p>
            <button onClick={retry} className="inline-flex items-center gap-1.5 text-[12px] text-brass hover:text-brass-bright">
              <RefreshCw size={12} /> Retry
            </button>
          </Card>
        ) : data ? (
          <>
            <Card variant="flat" className="mb-5 p-4">
              <p className="mb-3 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-faint">
                <Sparkles size={12} className="text-brass/70" /> What your assistant gains
              </p>
              <div className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
                {ABILITIES.map((a) => (
                  <div key={a.title} className="flex gap-2.5">
                    <a.icon size={15} className="mt-0.5 flex-shrink-0 text-brass/80" />
                    <div className="min-w-0">
                      <p className="text-[12.5px] font-medium text-paper">{a.title}</p>
                      <p className="text-[11.5px] leading-snug text-muted">{a.body}</p>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {!data.mcp_installed && (
              <Card variant="flat" className="mb-4 border-flag/25 p-3.5">
                <div className="flex items-start gap-2.5">
                  <ShieldAlert size={15} className="mt-0.5 flex-shrink-0 text-flag" />
                  <div className="min-w-0 text-[12.5px] leading-relaxed text-paper-dim">
                    <p className="font-medium text-paper">One-time install needed</p>
                    <p className="mt-0.5 text-muted">
                      The MCP support library isn't installed yet. Run this once in the
                      project, then reload this page:
                    </p>
                    <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2 font-mono text-[12px] text-paper">
                      <span>pip install mcp</span>
                      <CopyButton text="pip install mcp" />
                    </div>
                  </div>
                </div>
              </Card>
            )}
            {data.docker_hosts && (
              <Card variant="flat" className="mb-4 border-brass/25 p-3.5">
                <div className="flex items-start gap-2.5">
                  <ShieldAlert size={15} className="mt-0.5 flex-shrink-0 text-brass" />
                  <p className="text-[12.5px] leading-relaxed text-paper-dim">
                    Your databases look like they run inside Docker. The config below uses
                    those internal hostnames; if the connection fails, swap them for{" "}
                    <span className="font-mono text-brass">localhost</span> in the pasted
                    block (e.g. <span className="font-mono">bolt://localhost:7687</span>).
                  </p>
                </div>
              </Card>
            )}
            {!data.gemini_key_present && (
              <Card variant="flat" className="mb-4 border-brass/25 p-3.5">
                <div className="flex items-start gap-2.5">
                  <KeyRound size={15} className="mt-0.5 flex-shrink-0 text-brass" />
                  <p className="text-[12.5px] leading-relaxed text-paper-dim">
                    No <span className="font-mono">GEMINI_API_KEY</span> is set on the server,
                    so relationship queries and deep research won't work until you add one to
                    the pasted config.
                  </p>
                </div>
              </Card>
            )}

            <Card variant="flat" className="mb-5 flex items-center gap-2.5 px-4 py-3">
              <FolderOpen size={15} className="flex-shrink-0 text-brass/80" />
              <p className="text-[12.5px] text-muted">
                Your assistant will read the{" "}
                <span className="font-medium text-paper">{displayWorkspaceName}</span>{" "}
                workspace<span className="text-faint"> (id: {data.workspace_id})</span>.
                Switch workspaces (top-left) to generate a config for a different one.
              </p>
            </Card>

            <div className="mb-4 flex flex-wrap gap-1.5">
              {data.clients.map((c) => {
                const active = activeClient?.key === c.key;
                return (
                  <button
                    key={c.key}
                    onClick={() => setClientKey(c.key)}
                    className={`rounded-lg border px-3.5 py-2 text-[12.5px] font-medium transition-colors ${
                      active
                        ? "border-brass/40 bg-brass-dim text-brass"
                        : "border-ink-700 text-muted hover:border-ink-600 hover:text-paper-dim"
                    }`}
                  >
                    {c.label}
                  </button>
                );
              })}
            </div>

            {activeClient && (
              <Card variant="default" className="p-5">
                <Step n={1} icon={FolderOpen} title="Open the config">
                  {activeClient.config_path ? (
                    <>
                      <p>
                        In {activeClient.label}:{" "}
                        <span className="text-paper-dim">{activeClient.docs}</span>. It opens
                        (or creates) this file{activeClient.path_scope === "workspace" ? " in your project" : ""}:
                      </p>
                      <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2 font-mono text-[11.5px] text-paper-dim">
                        <span className="min-w-0 break-all">{activeClient.config_path}</span>
                        <CopyButton text={activeClient.config_path} label="Copy path" />
                      </div>
                    </>
                  ) : (
                    <p>
                      {activeClient.docs} The config goes wherever {activeClient.label} keeps
                      its MCP servers
                      {activeClient.filename && (
                        <> (e.g. a <span className="font-mono">{activeClient.filename}</span> file)</>
                      )}
                      .
                    </p>
                  )}
                </Step>

                <Step n={2} icon={ClipboardPaste} title="Paste this in">
                  <p>
                    {activeClient.format === "vscode" ? (
                      <>
                        Add the block below. If the file already has a{" "}
                        <span className="font-mono">servers</span> section, add just the{" "}
                        <span className="font-mono">"{data.server_name}"</span> entry inside it.
                      </>
                    ) : (
                      <>
                        Add the block below. If the file already has an{" "}
                        <span className="font-mono">mcpServers</span> section, add just the{" "}
                        <span className="font-mono">"{data.server_name}"</span> entry inside it.
                      </>
                    )}
                  </p>
                  <div className="mt-2 overflow-hidden rounded-lg border border-ink-700 bg-ink-950/60">
                    <div className="flex items-center justify-between border-b border-ink-700/70 px-3 py-1.5">
                      <span className="inline-flex items-center gap-1.5 text-[11px] text-faint">
                        <Terminal size={11} /> {activeClient.filename || `${data.server_name} (stdio)`}
                      </span>
                      <CopyButton text={configJson} label="Copy config" />
                    </div>
                    <pre className="max-h-72 overflow-auto scrollbar-thin px-3 py-2.5 font-mono text-[11px] leading-relaxed text-paper-dim">
{configJson}
                    </pre>
                  </div>
                  <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-faint">
                    <ShieldAlert size={12} className="mt-0.5 flex-shrink-0" />
                    This block includes your server's keys and settings; keep it private;
                    don't paste it into a shared or public place.
                  </p>
                </Step>

                <Step n={3} icon={RotateCw} title="Restart the app">
                  <p>
                    Fully restart {activeClient.label} (or reload its MCP servers). It will
                    launch this engine in the background and the new abilities appear
                    automatically. Try asking it something about your sources; it'll pull the
                    answer from here.
                  </p>
                </Step>

                <div className="-mt-6 flex gap-3.5">
                  <span className="w-7 flex-shrink-0" />
                  <p className="text-[11.5px] text-faint">
                    Runs entirely on your machine: <span className="font-mono">python -m backend.mcp.server</span>,
                    launched by the app on demand. Requires this engine's databases to be running,
                    same as the web app.
                  </p>
                </div>
              </Card>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
