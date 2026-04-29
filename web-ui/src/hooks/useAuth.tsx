import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type AuthState =
  | { status: "loading" }
  | { status: "needs-setup" }
  | { status: "anonymous" }
  | { status: "authenticated"; id: string; username: string; is_admin: boolean };

type AuthCtx = {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
  setupAdmin: (username: string, password: string, email?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

async function fetchMe(): Promise<AuthState> {
  const r = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (!r.ok) return { status: "anonymous" };
  const body = await r.json();
  if (body.authenticated) {
    return {
      status: "authenticated",
      id: body.id,
      username: body.username,
      is_admin: !!body.is_admin,
    };
  }
  if (body.needs_setup) {
    return { status: "needs-setup" };
  }
  return { status: "anonymous" };
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

  const setupAdmin = async (username: string, password: string, email?: string) => {
    const r = await fetch("/api/auth/setup-admin", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password, email }),
    });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(body || `setup-admin failed (${r.status})`);
    }
    // The backend already set the session cookie; refresh picks it up.
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

  return <Ctx.Provider value={{ state, login, setupAdmin, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
