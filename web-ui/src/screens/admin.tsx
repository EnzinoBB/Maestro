import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mono, Badge, Pill, Icons, relTime } from "../primitives";
import { PasswordStrength } from "../components/PasswordStrength";

type AdminUser = {
  id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
  created_at: number;
};

type AdminUsersResponse = { users: AdminUser[]; single_user_mode: boolean };
type Org = { id: string; name: string; created_at: number };

async function fetchUsers(): Promise<AdminUsersResponse> {
  const r = await fetch("/api/admin/users", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`users fetch failed: ${r.status}`);
  return r.json();
}

async function fetchOrgs(): Promise<{ orgs: Org[] }> {
  const r = await fetch("/api/orgs", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`orgs fetch failed: ${r.status}`);
  return r.json();
}

export function AdminScreen() {
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: fetchUsers, refetchInterval: 5000 });
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: fetchOrgs });
  const qc = useQueryClient();
  const [newOrgName, setNewOrgName] = useState("");
  const [orgError, setOrgError] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<AdminUser | null>(null);

  const onUserCreated = (id: string) => {
    setAddOpen(false);
    setHighlightId(id);
    qc.invalidateQueries({ queryKey: ["admin", "users"] });
    setTimeout(() => setHighlightId(null), 1500);
  };

  const createOrg = async () => {
    setOrgError(null);
    const r = await fetch("/api/orgs", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: newOrgName.trim() }),
    });
    if (!r.ok) {
      setOrgError(`failed: ${r.status}`);
      return;
    }
    setNewOrgName("");
    qc.invalidateQueries({ queryKey: ["orgs"] });
  };

  const userCount = users.data?.users.length ?? 0;
  const onlySystem = userCount === 1 && users.data?.users[0].username === "singleuser";

  return (
    <div className="cp-page">
      <header style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 16 }}>
        <h1>Admin</h1>
        {users.data?.single_user_mode && <Pill status="info">single-user mode</Pill>}
      </header>

      <section style={{ marginBottom: 28 }}>
        <div className="hstack" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <div className="cp-section-title">
            Users {users.data?.users && (<span className="dim mono">({userCount})</span>)}
          </div>
          {!users.data?.single_user_mode && (
            <button type="button" className="cp-btn cp-btn--primary cp-btn--sm"
              onClick={() => setAddOpen(o => !o)}>
              <Icons.plus size={12} />
              <span>{addOpen ? "Close" : "Add user"}</span>
            </button>
          )}
        </div>

        {addOpen && (
          <div className="cp-card" style={{
            marginBottom: 10, padding: 18,
            animation: "cp-slide-down 180ms ease-out",
          }}>
            <div className="hstack" style={{ justifyContent: "space-between", marginBottom: 14 }}>
              <div className="hstack" style={{ gap: 8 }}>
                <Icons.user size={14} />
                <strong>Add user</strong>
              </div>
              <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm"
                onClick={() => setAddOpen(false)}>
                <Icons.x size={12} />
              </button>
            </div>
            <AddUserForm onCancel={() => setAddOpen(false)} onSubmit={onUserCreated} />
          </div>
        )}

        {users.isLoading && <div className="cp-skel" style={{ height: 80 }} />}
        {users.error && (
          <div className="cp-empty">
            <p className="mono">{String(users.error)}</p>
            <p className="small dim">/api/admin/users requires admin (or single-user mode)</p>
          </div>
        )}
        {users.data && (
          <div className="cp-card">
            <table className="cp-table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>ID</th>
                  <th>Created</th>
                  <th style={{ width: 40 }}></th>
                </tr>
              </thead>
              <tbody>
                {users.data.users.map(u => {
                  const isSystem = u.username === "singleuser";
                  const highlight = highlightId === u.id;
                  return (
                    <tr key={u.id} style={highlight ? {
                      background: "color-mix(in oklch, var(--ok) 14%, transparent)",
                      transition: "background 1500ms ease-out",
                    } : undefined}>
                      <td>
                        <strong style={{
                          fontStyle: isSystem ? "italic" : undefined,
                          color: isSystem ? "var(--fg-muted)" : undefined,
                        }}>{u.username}</strong>
                        {isSystem && <Badge>{" "}system</Badge>}
                      </td>
                      <td>{u.email || <span className="dim">—</span>}</td>
                      <td>{u.is_admin
                        ? <Pill status="warning">admin</Pill>
                        : isSystem ? <span className="dim small">—</span> : <span className="small dim">member</span>}
                      </td>
                      <td><Mono dim>{u.id}</Mono></td>
                      <td className="small dim">{relTime(u.created_at)}</td>
                      <td>
                        {!isSystem && (
                          <div style={{ position: "relative" }}>
                            <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm"
                              onClick={() => setMenuFor(menuFor === u.id ? null : u.id)}>
                              <Icons.more size={12} />
                            </button>
                            {menuFor === u.id && (
                              <>
                                <div onClick={() => setMenuFor(null)}
                                  style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                                <div className="cp-popover" style={{
                                  position: "absolute", right: 0, top: 28,
                                  zIndex: 31, minWidth: 180, padding: 4,
                                }}>
                                  <button type="button" className="cp-btn cp-btn--ghost"
                                    style={{ width: "100%", justifyContent: "flex-start", padding: "6px 10px", gap: 8 }}
                                    onClick={() => { setResetFor(u); setMenuFor(null); }}>
                                    <Icons.rotate size={12} />
                                    <span>Reset password</span>
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
            {onlySystem && (
              <div style={{
                padding: 14, borderTop: "1px solid var(--border)",
                display: "flex", alignItems: "center", gap: 12, background: "var(--bg-2)",
              }}>
                <Icons.user size={16} />
                <div className="grow">
                  <div style={{ fontWeight: 500 }}>You're the only user.</div>
                  <div className="small dim">
                    Click <Mono>+ Add user</Mono> to invite collaborators.
                    They'll be able to apply deploys and manage their own nodes.
                  </div>
                </div>
                {!users.data.single_user_mode && (
                  <button type="button" className="cp-btn cp-btn--primary cp-btn--sm"
                    onClick={() => setAddOpen(true)}>
                    <Icons.plus size={12} />
                    <span>Add user</span>
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <div className="cp-section-title" style={{ marginBottom: 10 }}>
          Organizations {orgs.data?.orgs && (<span className="dim mono">({orgs.data.orgs.length})</span>)}
        </div>
        <form
          onSubmit={e => { e.preventDefault(); if (newOrgName.trim()) createOrg(); }}
          style={{ display: "flex", gap: 6, marginBottom: 10, maxWidth: 480 }}
        >
          <input className="cp-input cp-input--mono" placeholder="new org name…"
            value={newOrgName} onChange={e => setNewOrgName(e.target.value)} />
          <button type="submit" className="cp-btn cp-btn--primary" disabled={!newOrgName.trim()}>
            <Icons.plus size={12} />
            <span>Create</span>
          </button>
        </form>
        {orgError && <div className="small mono" style={{ color: "var(--err)", marginBottom: 8 }}>{orgError}</div>}
        {orgs.isLoading && <div className="cp-skel" style={{ height: 80 }} />}
        {orgs.data && orgs.data.orgs.length === 0 && (
          <div className="small dim">No organizations yet — shared nodes need an owner org.</div>
        )}
        {orgs.data && orgs.data.orgs.length > 0 && (
          <table className="cp-table">
            <thead>
              <tr><th>Name</th><th>ID</th><th>Created</th></tr>
            </thead>
            <tbody>
              {orgs.data.orgs.map(o => (
                <tr key={o.id}>
                  <td><strong>{o.name}</strong></td>
                  <td><Mono dim>{o.id}</Mono></td>
                  <td className="small dim">{relTime(o.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {resetFor && <ResetPasswordModal user={resetFor} onClose={() => setResetFor(null)} />}
    </div>
  );
}

function AddUserForm({ onCancel, onSubmit }: {
  onCancel: () => void;
  onSubmit: (id: string) => void;
}) {
  const [u, setU] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [show, setShow] = useState(false);
  const [admin, setAdmin] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const valid = /^[a-z0-9-]{2,}$/.test(u) && pw.length >= 8;

  const submit = async () => {
    if (!valid) { setErr("Username (dns-1123) and 8+ char password required"); return; }
    setErr(null);
    setSubmitting(true);
    try {
      const r = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          username: u,
          password: pw,
          email: email || null,
          is_admin: admin,
        }),
      });
      if (!r.ok) {
        const body = await r.text();
        throw new Error(body || `create failed (${r.status})`);
      }
      const created = await r.json();
      onSubmit(created.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="vstack" style={{ gap: 14 }}>
      <div>
        <div className="cp-label" style={{ marginBottom: 6 }}>Username</div>
        <input className="cp-input cp-input--mono" value={u}
          onChange={e => setU(e.target.value.toLowerCase())} placeholder="alice" autoFocus />
        <div className="small dim mono" style={{ marginTop: 4 }}>
          dns-1123: lowercase, digits, hyphens · 2+ chars
        </div>
      </div>
      <div>
        <div className="cp-label" style={{ marginBottom: 6 }}>
          Email <span className="dim" style={{ textTransform: "none", letterSpacing: 0 }}>(optional)</span>
        </div>
        <input className="cp-input cp-input--mono" value={email}
          onChange={e => setEmail(e.target.value)} placeholder="alice@example.com" />
      </div>
      <div>
        <div className="hstack" style={{ justifyContent: "space-between", marginBottom: 6 }}>
          <span className="cp-label">Password</span>
          <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm"
            onClick={() => setShow(!show)}>{show ? "hide" : "show"}</button>
        </div>
        <input className="cp-input cp-input--mono" value={pw}
          onChange={e => { setPw(e.target.value); setErr(null); }}
          type={show ? "text" : "password"} />
        <PasswordStrength value={pw} />
      </div>
      <label className="hstack" style={{
        gap: 8, padding: "8px 10px",
        border: "1px solid var(--border)", borderRadius: 4, cursor: "pointer",
      }}>
        <input type="checkbox" checked={admin} onChange={e => setAdmin(e.target.checked)} />
        <div className="grow">
          <div style={{ fontWeight: 500 }}>Make this user an admin</div>
          <div className="small dim">
            Admins can add users, manage shared nodes, and reset other users' passwords.
          </div>
        </div>
      </label>
      {err && <div style={{ color: "var(--err)", fontSize: 11 }}>{err}</div>}
      <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, paddingTop: 6 }}>
        <button type="button" className="cp-btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="cp-btn cp-btn--primary"
          disabled={!valid || submitting} onClick={submit}>
          <Icons.check size={12} />
          <span>{submitting ? "Creating…" : "Create user"}</span>
        </button>
      </div>
    </div>
  );
}

function ResetPasswordModal({ user, onClose }: {
  user: AdminUser;
  onClose: () => void;
}) {
  const [pw, setPw] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [generating, setGenerating] = useState(false);

  const generate = async () => {
    setGenerating(true);
    setErr(null);
    try {
      const r = await fetch(`/api/admin/users/${user.id}/reset-password`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (!r.ok) throw new Error(`reset failed (${r.status})`);
      const body = await r.json();
      setPw(body.new_password);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const copy = async () => {
    if (!pw) return;
    try {
      await navigator.clipboard.writeText(pw);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  };

  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onClose} />
      <div className="cp-modal" style={{ zIndex: 70, width: 460 }}>
        <div className="cp-drawer__header">
          <Icons.rotate size={14} />
          <div className="grow">
            <strong>Reset password</strong>{" "}
            <Mono dim style={{ marginLeft: 8, fontSize: 11 }}>@{user.username}</Mono>
          </div>
          <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose}>
            <Icons.x size={14} />
          </button>
        </div>
        <div style={{ padding: 16 }}>
          {!pw && (
            <div>
              <div className="small dim" style={{ marginBottom: 12, lineHeight: 1.5 }}>
                Generates a new password for <Mono>@{user.username}</Mono>. The user's existing
                password is invalidated immediately. The new password is shown <strong>once</strong>;
                copy it and share it via a secure channel.
              </div>
              {err && (
                <div className="small mono" style={{ color: "var(--err)", marginBottom: 8 }}>{err}</div>
              )}
              <div className="hstack" style={{ justifyContent: "flex-end", gap: 8 }}>
                <button type="button" className="cp-btn" onClick={onClose}>Cancel</button>
                <button type="button" className="cp-btn cp-btn--primary"
                  disabled={generating} onClick={generate}>
                  <Icons.rotate size={12} />
                  <span>{generating ? "Generating…" : "Generate new password"}</span>
                </button>
              </div>
            </div>
          )}
          {pw && (
            <div>
              <div className="small dim" style={{ marginBottom: 10 }}>
                Copy this and hand it to the user. Maestro does not store the plaintext.
              </div>
              <div className="hstack" style={{
                gap: 8, padding: 10,
                border: "1px solid var(--border)", borderRadius: 4, background: "var(--bg)",
              }}>
                <Mono style={{ flex: 1, fontSize: 13 }}>{pw}</Mono>
                <button type="button" className="cp-btn cp-btn--sm" onClick={copy}>
                  <Icons.check size={12} />
                  <span>{copied ? "copied" : "copy"}</span>
                </button>
              </div>
              <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
                <button type="button" className="cp-btn cp-btn--primary" onClick={onClose}>Done</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
