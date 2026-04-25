import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mono, Pill, Icons, relTime } from "../primitives";

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
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: fetchUsers });
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: fetchOrgs });
  const qc = useQueryClient();
  const [newOrgName, setNewOrgName] = useState("");
  const [orgError, setOrgError] = useState<string | null>(null);

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

  return (
    <div className="cp-page">
      <header style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 16 }}>
        <h1>Admin</h1>
        {users.data?.single_user_mode && (
          <Pill status="info">single-user mode</Pill>
        )}
      </header>

      <section style={{ marginBottom: 28 }}>
        <div className="cp-section-title" style={{ marginBottom: 10 }}>
          Users {users.data?.users && (<span className="dim mono">({users.data.users.length})</span>)}
        </div>
        {users.isLoading && <div className="cp-skel" style={{ height: 80 }} />}
        {users.error && (
          <div className="cp-empty">
            <p className="mono">{String(users.error)}</p>
            <p className="small dim">/api/admin/users requires admin (or single-user mode)</p>
          </div>
        )}
        {users.data && (
          <table className="cp-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Email</th>
                <th>Role</th>
                <th>ID</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {users.data.users.map(u => (
                <tr key={u.id}>
                  <td><strong>{u.username}</strong></td>
                  <td>{u.email || <span className="dim">—</span>}</td>
                  <td>{u.is_admin ? <Pill status="warning">admin</Pill> : <span className="small dim">member</span>}</td>
                  <td><Mono dim>{u.id}</Mono></td>
                  <td className="small dim">{relTime(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
    </div>
  );
}
