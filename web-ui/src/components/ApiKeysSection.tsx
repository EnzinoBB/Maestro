import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { GenerateApiKeyDialog } from "./GenerateApiKeyDialog";
import { RevokeApiKeyDialog } from "./RevokeApiKeyDialog";

type ApiKey = {
  id: string;
  label: string;
  prefix: string;
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
};

async function fetchKeys(): Promise<ApiKey[]> {
  const r = await fetch("/api/auth/keys", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`failed to fetch keys (${r.status})`);
  const body = await r.json();
  return body.keys;
}

async function revokeKey(id: string): Promise<void> {
  const r = await fetch(`/api/auth/keys/${id}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`failed to revoke (${r.status})`);
  }
}

function relativeTime(ts: number | null): string {
  if (!ts) return "never";
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function ApiKeysSection() {
  const qc = useQueryClient();
  const { data: keys = [], isLoading } = useQuery({
    queryKey: ["api-keys"], queryFn: fetchKeys,
  });
  const [generating, setGenerating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const revokeMut = useMutation({
    mutationFn: revokeKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  if (isLoading) return <p>Loading…</p>;

  return (
    <div>
      <p style={{ color: "#888", marginBottom: 12 }}>
        API keys allow external tools (like the Claude Code MCP server) to
        access Maestro on your behalf. Anyone with a key has the same
        permissions as you do — keep them secret.
      </p>

      <button onClick={() => setGenerating(true)}>Generate API key</button>

      {keys.length === 0 ? (
        <p style={{ marginTop: 16 }}>No API keys yet.</p>
      ) : (
        <table style={{ marginTop: 16, width: "100%" }}>
          <thead>
            <tr>
              <th>Label</th>
              <th>Prefix</th>
              <th>Created</th>
              <th>Last used</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {keys.map(k => (
              <tr key={k.id}>
                <td>{k.label}</td>
                <td><code>{k.prefix}…</code></td>
                <td>{relativeTime(k.created_at)}</td>
                <td>{relativeTime(k.last_used_at)}</td>
                <td>
                  {k.revoked_at == null
                    ? <span style={{ color: "green" }}>active</span>
                    : <span style={{ color: "#888" }}>revoked</span>}
                </td>
                <td>
                  {k.revoked_at == null && (
                    <button onClick={() => setRevoking(k)}>Revoke</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {generating && (
        <GenerateApiKeyDialog onClose={() => {
          setGenerating(false);
          qc.invalidateQueries({ queryKey: ["api-keys"] });
        }} />
      )}

      {revoking && (
        <RevokeApiKeyDialog
          label={revoking.label}
          onConfirm={async () => {
            await revokeMut.mutateAsync(revoking.id);
            setRevoking(null);
          }}
          onClose={() => setRevoking(null)}
        />
      )}
    </div>
  );
}
