import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const BASE = ""; // served from same origin; in dev, Vite proxies /api

export type Deploy = {
  id: string;
  name: string;
  owner_user_id: string;
  current_version: number | null;
  state_summary: unknown;
  created_at: number;
  updated_at: number;
};

export type DeployVersion = {
  id: string;
  version_n: number;
  yaml_text: string;
  components_hash: string;
  parent_version_id: string | null;
  applied_at: number;
  applied_by_user_id: string;
  result_json: { ok?: boolean; error?: string | null } | null;
  kind: "apply" | "rollback";
};

export type DeployWithVersions = Deploy & { versions: DeployVersion[] };

export type Host = { host_id: string; online: boolean; system: Record<string, unknown> };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${text}`);
  }
  return r.json();
}

// ----- Hooks -----

export function useDeploys() {
  return useQuery({
    queryKey: ["deploys"],
    queryFn: () => api<{ deploys: Deploy[] }>("/api/deploys"),
    refetchInterval: 5000,
  });
}

export function useDeploy(id: string | undefined) {
  return useQuery({
    queryKey: ["deploy", id],
    queryFn: () => api<DeployWithVersions>(`/api/deploys/${id}`),
    enabled: !!id,
    refetchInterval: 5000,
  });
}

export function useHosts() {
  return useQuery({
    queryKey: ["hosts"],
    queryFn: () => api<{ hosts: Host[] }>("/api/hosts"),
    refetchInterval: 5000,
  });
}

export function useCreateDeploy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api<Deploy>("/api/deploys", { method: "POST", body: JSON.stringify({ name }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deploys"] }),
  });
}

export function useDeleteDeploy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await fetch(`/api/deploys/${id}`, { method: "DELETE" });
      if (!r.ok && r.status !== 204) throw new Error(`delete failed: ${r.status}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deploys"] }),
  });
}

export function useRollback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deployId, versionN }: { deployId: string; versionN: number }) =>
      api(`/api/deploys/${deployId}/rollback/${versionN}`, { method: "POST" }),
    onSuccess: (_r, { deployId }) => {
      qc.invalidateQueries({ queryKey: ["deploy", deployId] });
      qc.invalidateQueries({ queryKey: ["deploys"] });
    },
  });
}

// ----- Helpers -----

/** Derive a single health label from versions + result_json of the latest one. */
export function deployHealth(d: Deploy, versions?: DeployVersion[]): {
  status: "healthy" | "degraded" | "failed" | "unknown";
  label: string;
} {
  if (d.current_version == null) return { status: "unknown", label: "No version applied" };
  const latest = versions?.find(v => v.version_n === d.current_version);
  if (!latest) return { status: "unknown", label: "Unknown" };
  const ok = latest.result_json?.ok;
  if (ok === true) return { status: "healthy", label: "Healthy" };
  if (ok === false) return { status: "failed", label: "Last apply failed" };
  return { status: "unknown", label: "Unknown" };
}
