import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type AuthState =
  | { status: "loading" }
  | { status: "single-user"; id: string; username: string; is_admin: boolean }
  | { status: "anonymous"; single_user_mode: boolean }
  | { status: "authenticated"; id: string; username: string; is_admin: boolean };

type AuthCtx = {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

async function fetchMe(): Promise<AuthState> {
  const r = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (!r.ok) return { status: "anonymous", single_user_mode: false };
  const body = await r.json();
  if (body.authenticated && body.single_user_mode) {
    return { status: "single-user", id: body.id, username: body.username, is_admin: !!body.is_admin };
  }
  if (body.authenticated) {
    return { status: "authenticated", id: body.id, username: body.username, is_admin: !!body.is_admin };
  }
  return { status: "anonymous", single_user_mode: !!body.single_user_mode };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const qc = useQueryClient();

  const refresh = async () => {
    const next = await fetchMe();
    setState(next);
    qc.invalidateQueries();
  };

  const login = async (username: string, password: string) => {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(body || `login failed (${r.status})`);
    }
    await refresh();
  };

  const logout = async () => {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
    await refresh();
  };

  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return <Ctx.Provider value={{ state, login, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
