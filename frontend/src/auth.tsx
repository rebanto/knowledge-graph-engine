import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getMe, login as apiLogin, logout as apiLogout, register as apiRegister } from "./api";
import type { User } from "./types";

type AuthStatus = "loading" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);

  const markAnonymous = useCallback(() => {
    setUser(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    let alive = true;
    getMe()
      .then((me) => {
        if (!alive) return;
        setUser(me);
        setStatus("authenticated");
      })
      .catch(() => {
        if (alive) markAnonymous();
      });
    return () => {
      alive = false;
    };
  }, [markAnonymous]);

  useEffect(() => {
    const onLogout = () => markAnonymous();
    window.addEventListener("kgre:logout", onLogout);
    return () => window.removeEventListener("kgre:logout", onLogout);
  }, [markAnonymous]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      async login(email, password) {
        const me = await apiLogin(email, password);
        setUser(me);
        setStatus("authenticated");
      },
      async register(email, password) {
        const me = await apiRegister(email, password);
        setUser(me);
        setStatus("authenticated");
      },
      async logout() {
        try {
          await apiLogout();
        } finally {
          window.dispatchEvent(new CustomEvent("kgre:logout"));
          markAnonymous();
        }
      },
    }),
    [markAnonymous, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
