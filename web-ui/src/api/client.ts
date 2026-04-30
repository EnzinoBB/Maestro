import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const BASE = ""; // served from same origin; in dev, Vite proxies /api

export type Deploy = {
  id: string;
  name: string;
  owner_user_id: string;
  owner_username: string | null;
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
  applied_by_username: string | null;
  result_json: { ok?: boolean; error?: string | null } | null;
  kind: "apply" | "rollback";
};

export type DeployWithVersions = Deploy & { versions: DeployVersion[] };

export type Host = { host_id: string; online: boolean; system: Record<string, unknown> };

export type Node = {
  id: string;
  host_id: string;
  node_type: "user" | "shared";
  owner_user_id: string | null;
  owner_username: string | null;
  owner_org_id: string | null;
  label: string | null;
  created_at: number;
  online: boolean;
};

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

export function useNodes() {
  return useQuery({
    queryKey: ["nodes"],
    queryFn: () => api<{ nodes: Node[] }>("/api/nodes"),
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

export type NodeUpdate = {
  node_type?: "user" | "shared";
  owner_user_id?: string | null;
  owner_org_id?: string | null;
  label?: string | null;
};

export function useUpdateNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: NodeUpdate }) => {
      const r = await fetch(`/api/nodes/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(patch),
        credentials: "same-origin",
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`update failed (${r.status}): ${text}`);
      }
      return r.json() as Promise<Node>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["nodes"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: { is_admin?: boolean } }) => {
      const r = await fetch(`/api/admin/users/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(patch),
        credentials: "same-origin",
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`update failed (${r.status}): ${text}`);
      }
      return r.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export type DeleteUserError = {
  status: number;
  code?: string;
  message: string;
  deploys?: number;
  nodes?: number;
};

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation<void, DeleteUserError, string>({
    mutationFn: async (id: string) => {
      const r = await fetch(`/api/admin/users/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (r.status === 204) return;
      let body: unknown = null;
      try { body = await r.json(); } catch { /* not json */ }
      const detail = (body as { detail?: unknown } | null)?.detail;
      if (detail && typeof detail === "object" && "code" in detail) {
        const d = detail as { code?: string; message?: string; deploys?: number; nodes?: number };
        throw {
          status: r.status, code: d.code, message: d.message ?? "delete failed",
          deploys: d.deploys, nodes: d.nodes,
        } satisfies DeleteUserError;
      }
      throw {
        status: r.status,
        message: typeof detail === "string" ? detail : `delete failed (${r.status})`,
      } satisfies DeleteUserError;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
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

// ----- Metrics hooks -----

export type MetricPoint = [number, number]; // [ts_seconds, value]

async function apiMetricRange(
  scope: "host" | "component" | "deploy",
  scopeId: string,
  metric: string,
  fromTs: number,
  toTs: number,
): Promise<MetricPoint[]> {
  const u = new URL(`${location.origin}/api/metrics/${scope}/${encodeURIComponent(scopeId)}`);
  u.searchParams.set("metric", metric);
  u.searchParams.set("from_ts", String(fromTs));
  u.searchParams.set("to_ts", String(toTs));
  const r = await fetch(u.pathname + u.search);
  if (!r.ok) throw new Error(`metrics fetch failed: ${r.status}`);
  const body = await r.json();
  return body.points || [];
}

export function useMetricRange(
  scope: "host" | "component" | "deploy",
  scopeId: string,
  metric: string,
  windowSeconds = 15 * 60,
  enabled = true,
) {
  return useQuery({
    queryKey: ["metrics", scope, scopeId, metric, windowSeconds],
    enabled,
    queryFn: async () => {
      const now = Date.now() / 1000;
      return apiMetricRange(scope, scopeId, metric, now - windowSeconds, now);
    },
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

export function useHostCpuSeries(hostId: string, windowSeconds = 15 * 60, enabled = true) {
  return useMetricRange("host", hostId, "cpu_percent", windowSeconds, enabled);
}

export function useComponentMetric(
  componentId: string,
  metric: string,
  windowSeconds = 15 * 60,
  enabled = true,
) {
  return useMetricRange("component", componentId, metric, windowSeconds, enabled);
}

// ----- Wizard helpers -----

export type DockerSuggestions = {
  exposed_ports: number[];
  env: { key: string; value: string }[];
  volumes: string[];
};

export async function postDockerInspect(image: string, tag: string): Promise<DockerSuggestions> {
  const r = await fetch("/api/wizard/docker/inspect", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ image, tag }),
  });
  if (!r.ok) throw new Error(`inspect failed: ${r.status}`);
  return r.json();
}
