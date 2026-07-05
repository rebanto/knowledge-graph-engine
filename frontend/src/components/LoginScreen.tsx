import axios from "axios";
import { ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";

import { useAuth } from "../auth";
import { BRASS } from "../lib/palette";
import { Button, Card, Input, SectionLabel } from "./ui";

function describeAuthError(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (!err.response) return "Couldn't reach the backend.";
  }
  return "Authentication failed.";
}

export function LoginScreen() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password);
    } catch (err) {
      setError(describeAuthError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-ink-950 px-6 text-paper">
      <div className="app-aura" />
      <div className="app-vignette" />
      <Card className="relative z-10 w-full max-w-[390px] p-6">
        <SectionLabel>Knowledge Graph Engine</SectionLabel>
        <h1 className="mt-3 font-display text-[24px] font-medium leading-tight text-paper">
          {mode === "login" ? "Sign in" : "Create account"}
        </h1>
        <p className="mt-2 text-[13px] leading-relaxed text-muted">
          Your workspaces, reports, and threads are stored under your account.
        </p>

        <div className="mt-5 grid grid-cols-2 rounded-lg border border-ink-700 bg-ink-900 p-1">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors ${
              mode === "login" ? "bg-ink-750 text-paper" : "text-muted hover:text-paper-dim"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors ${
              mode === "register" ? "bg-ink-750 text-paper" : "text-muted hover:text-paper-dim"
            }`}
          >
            New account
          </button>
        </div>

        <form onSubmit={onSubmit} className="mt-5 space-y-3">
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.12em] text-faint">
              Email
            </span>
            <Input
              autoFocus
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.12em] text-faint">
              Password
            </span>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              minLength={8}
              required
            />
          </label>

          {error && <p className="text-[12.5px] text-flag">{error}</p>}

          <Button type="submit" variant="primary" className="w-full" disabled={busy}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowRight size={14} />}
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>

        <div
          className="mt-5 h-px w-full"
          style={{ background: `linear-gradient(90deg, transparent, ${BRASS}55, transparent)` }}
        />
      </Card>
    </div>
  );
}
