import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Icons, Mono, Pill, StatusDot, relTime } from "../primitives";
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

function fmtAbs(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toISOString().replace("T", " ").replace(/\..+/, " UTC");
}

export function ApiKeysSection() {
  const qc = useQueryClient();
  const { data: keys, isLoading } = useQuery({
    queryKey: ["api-keys"], queryFn: fetchKeys,
  });
  const [generating, setGenerating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const revokeMut = useMutation({
    mutationFn: revokeKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  const list = keys ?? [];
  const total = list.length;

  return (
    <section className="cp-settings-section">
      <div className="cp-settings-sectionhead">
        <div className="vstack" style={{ gap: 2 }}>
          <span className="cp-section-title">
            API keys
            {!isLoading && (
              <span className="mono dim" style={{ marginLeft: 4 }}>({total})</span>
            )}
          </span>
          <span className="dim small">
            Long-lived credentials used by the MCP server and other automation clients.
          </span>
        </div>
        <div className="hstack" style={{ gap: 6 }}>
          <button
            type="button"
            className="cp-btn cp-btn--primary cp-btn--sm"
            onClick={() => setGenerating(true)}
          >
            <Icons.plus size={11} />
            <span>Generate API key</span>
          </button>
        </div>
      </div>

      <div className="cp-settings-callout">
        <Icons.alert size={13} className="cp-settings-callout__icon" />
        <span className="small" style={{ lineHeight: 1.55 }}>
          Keys grant the <strong>same permissions as the user</strong>. Treat them like
          passwords — store in a secret manager, rotate when an integration changes hands,
          revoke immediately if exposed.
        </span>
      </div>

      {isLoading && (
        <div className="cp-card" style={{ padding: 14 }}>
          <div className="vstack" style={{ gap: 8 }}>
            {[0, 1, 2].map(i => (
              <div key={i} className="hstack" style={{ gap: 12 }}>
                <div className="cp-skel" style={{ width: 140, height: 12 }} />
                <div className="cp-skel" style={{ width: 100, height: 12 }} />
                <div className="cp-skel" style={{ width: 80, height: 12 }} />
                <div className="grow" />
                <div className="cp-skel" style={{ width: 60, height: 12 }} />
              </div>
            ))}
          </div>
        </div>
      )}

      {!isLoading && total === 0 && (
        <div className="cp-empty cp-settings-empty">
          <div className="cp-settings-empty__icon">
            <Icons.key size={20} />
          </div>
          <h2 style={{ fontSize: 14, marginBottom: 4 }}>No API keys yet</h2>
          <p className="small">
            Generate a key to authenticate the MCP server, CI runners, or other automation
            clients against this Control Plane.
          </p>
          <button
            type="button"
            className="cp-btn cp-btn--primary cp-btn--sm"
            onClick={() => setGenerating(true)}
          >
            <Icons.plus size={11} />
            <span>Generate API key</span>
          </button>
        </div>
      )}

      {!isLoading && total > 0 && (
        <div className="cp-card" style={{ overflow: "hidden" }}>
          <table className="cp-table cp-settings-keytable">
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
              {list.map(k => {
                const revoked = !!k.revoked_at;
                return (
                  <tr key={k.id} className={revoked ? "is-revoked" : ""}>
                    <td>
                      <strong style={{ fontSize: 12.5 }}>{k.label}</strong>
                    </td>
                    <td>
                      <Mono dim style={{ fontSize: 11 }}>{k.prefix}…</Mono>
                    </td>
                    <td title={fmtAbs(k.created_at)}>
                      <Mono dim style={{ fontSize: 11 }}>{relTime(k.created_at)}</Mono>
                    </td>
                    <td title={k.last_used_at ? fmtAbs(k.last_used_at) : "never used"}>
                      {k.last_used_at
                        ? <Mono dim style={{ fontSize: 11 }}>{relTime(k.last_used_at)}</Mono>
                        : <span className="dim small">never</span>}
                    </td>
                    <td>
                      {revoked ? (
                        <span className="cp-settings-statneutral">
                          <StatusDot status="unknown" size={6} />
                          revoked
                        </span>
                      ) : (
                        <Pill status="healthy">active</Pill>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {!revoked && (
                        <div style={{ position: "relative", display: "inline-block" }}>
                          <button
                            type="button"
                            className="cp-btn cp-btn--ghost cp-btn--sm"
                            aria-label="Row actions"
                            onClick={() => setMenuFor(menuFor === k.id ? null : k.id)}
                          >
                            <Icons.more size={12} />
                          </button>
                          {menuFor === k.id && (
                            <>
                              <div
                                onClick={() => setMenuFor(null)}
                                style={{ position: "fixed", inset: 0, zIndex: 30 }}
                              />
                              <div className="cp-settings-menu">
                                <button
                                  type="button"
                                  className="cp-settings-menu__item is-danger"
                                  onClick={() => { setRevoking(k); setMenuFor(null); }}
                                >
                                  <Icons.trash size={11} />
                                  <span>Revoke key</span>
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
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
    </section>
  );
}
