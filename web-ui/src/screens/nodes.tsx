import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mono, Pill, Icons, StatusDot, relTime, Sparkline } from "../primitives";
import { useHostCpuSeries, useNodes, useUpdateNode, type Node } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { EnrollDrawer, NodesEmpty } from "../components/EnrollDrawer";

export function NodesScreen() {
  const { state } = useAuth();
  const isAdmin = state.status === "authenticated" && state.is_admin;
  const [enrollOpen, setEnrollOpen] = useState(false);
  const [knownAtOpen, setKnownAtOpen] = useState<Set<string>>(new Set());

  const { data, isLoading, error } = useNodes();
  const nodes = data?.nodes ?? [];

  const openEnroll = useMemo(() => () => {
    setKnownAtOpen(new Set(nodes.map(n => n.host_id)));
    setEnrollOpen(true);
  }, [nodes]);

  return (
    <div className="cp-page">
      <header style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 16 }}>
        <h1>Nodes</h1>
        <span className="small dim mono">
          {nodes.length} total · {nodes.filter(n => n.online).length} online
        </span>
        <div style={{ flex: 1 }} />
        <button type="button" className="cp-btn cp-btn--primary" onClick={openEnroll}>
          <Icons.plus size={12} />
          <span>Enroll new daemon</span>
        </button>
      </header>

      {isLoading && <div className="cp-skel" style={{ height: 120 }} />}
      {error && (
        <div className="cp-empty">
          <h2>Could not load nodes</h2>
          <p className="mono">{String(error)}</p>
        </div>
      )}

      {!isLoading && !error && nodes.length === 0 && (
        <NodesEmpty onEnroll={openEnroll} isAdmin={true} />
      )}

      {nodes.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))",
          gap: 12,
        }}>
          {nodes.map(n => <NodeCard key={n.id} node={n} isAdmin={isAdmin} />)}
        </div>
      )}

      {enrollOpen && (
        <EnrollDrawer
          onClose={() => setEnrollOpen(false)}
          knownHostIds={knownAtOpen}
        />
      )}
    </div>
  );
}

function NodeCard({ node, isAdmin }: { node: Node; isAdmin: boolean }) {
  const display = node.label || node.host_id;
  const ownerLabel = node.node_type === "shared"
    ? `org ${node.owner_org_id}`
    : (node.owner_username ? `@${node.owner_username}` : node.owner_user_id);
  const ownerTitle = node.node_type === "shared"
    ? (node.owner_org_id ?? undefined)
    : (node.owner_user_id ?? undefined);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pivotOpen, setPivotOpen] = useState(false);
  const [labelOpen, setLabelOpen] = useState(false);
  return (
    <div className="cp-card" style={{ padding: 14, position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <StatusDot status={node.online ? "online" : "offline"} size={8} />
        <strong style={{ fontSize: 14 }}>{display}</strong>
        <div style={{ flex: 1 }} />
        <Pill status={node.node_type === "shared" ? "info" : "success"}>
          {node.node_type}
        </Pill>
        {isAdmin && (
          <div style={{ position: "relative" }}>
            <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm"
              aria-label="Node actions"
              onClick={() => setMenuOpen(o => !o)}>
              <Icons.more size={12} />
            </button>
            {menuOpen && (
              <>
                <div onClick={() => setMenuOpen(false)}
                  style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                <div className="cp-popover" style={{
                  position: "absolute", right: 0, top: 28,
                  zIndex: 31, minWidth: 200, padding: 4,
                }}>
                  <button type="button" className="cp-btn cp-btn--ghost"
                    style={{ width: "100%", justifyContent: "flex-start", padding: "6px 10px", gap: 8 }}
                    onClick={() => { setPivotOpen(true); setMenuOpen(false); }}>
                    <Icons.rotate size={12} />
                    <span>{node.node_type === "user" ? "Promote to shared" : "Demote to user"}</span>
                  </button>
                  <button type="button" className="cp-btn cp-btn--ghost"
                    style={{ width: "100%", justifyContent: "flex-start", padding: "6px 10px", gap: 8 }}
                    onClick={() => { setLabelOpen(true); setMenuOpen(false); }}>
                    <Icons.user size={12} />
                    <span>Edit label</span>
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
      <div className="small dim mono" style={{ marginBottom: 8 }}>
        host_id: {node.host_id} · owned by{" "}
        <span title={ownerTitle}>{ownerLabel}</span>
        {" "}· created {relTime(node.created_at)}
      </div>
      <NodeMiniMetrics hostId={node.host_id} online={node.online} />

      {pivotOpen && (
        <NodePivotModal node={node} onClose={() => setPivotOpen(false)} />
      )}
      {labelOpen && (
        <NodeLabelModal node={node} onClose={() => setLabelOpen(false)} />
      )}
    </div>
  );
}

function NodeMiniMetrics({ hostId, online }: { hostId: string; online: boolean }) {
  const { data } = useHostCpuSeries(hostId, 15 * 60, online);
  const series = (data || []).map(([t, v]) => ({ t, v }));
  if (!online) {
    return (
      <div className="small dim" style={{ height: 30, display: "flex", alignItems: "center" }}>
        <Icons.alert size={11} /> &nbsp; daemon offline
      </div>
    );
  }
  if (series.length === 0) {
    return (
      <div className="small dim" style={{ height: 30, display: "flex", alignItems: "center" }}>
        no samples in window
      </div>
    );
  }
  const last = series[series.length - 1].v;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span className="small dim">CPU</span>
      <Mono style={{ fontSize: 12 }}>{last.toFixed(1)}%</Mono>
      <div style={{ flex: 1 }}>
        <Sparkline data={series} width={220} height={30} />
      </div>
    </div>
  );
}

type Org = { id: string; name: string };
type AdminUser = { id: string; username: string };

function useOrgs() {
  return useQuery({
    queryKey: ["orgs"],
    queryFn: async () => {
      const r = await fetch("/api/orgs", { credentials: "same-origin" });
      if (!r.ok) throw new Error(`orgs fetch failed: ${r.status}`);
      const body = await r.json();
      return body.orgs as Org[];
    },
  });
}

function useAdminUsers() {
  return useQuery({
    queryKey: ["admin", "users"],
    queryFn: async () => {
      const r = await fetch("/api/admin/users", { credentials: "same-origin" });
      if (!r.ok) throw new Error(`users fetch failed: ${r.status}`);
      const body = await r.json();
      return body.users as AdminUser[];
    },
  });
}

function NodePivotModal({ node, onClose }: { node: Node; onClose: () => void }) {
  const target = node.node_type === "user" ? "shared" : "user";
  const orgs = useOrgs();
  const users = useAdminUsers();
  const update = useUpdateNode();
  const [orgId, setOrgId] = useState("");
  const [userId, setUserId] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = () => {
    setErr(null);
    if (target === "shared" && !orgId) { setErr("Pick an org first"); return; }
    if (target === "user" && !userId) { setErr("Pick a user first"); return; }
    const patch = target === "shared"
      ? { node_type: "shared" as const, owner_org_id: orgId }
      : { node_type: "user" as const, owner_user_id: userId };
    update.mutate({ id: node.id, patch }, {
      onSuccess: onClose,
      onError: e => setErr(e instanceof Error ? e.message : String(e)),
    });
  };

  const orgList = orgs.data ?? [];
  const userList = (users.data ?? []).filter(u => u.username !== "singleuser");

  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onClose} />
      <div className="cp-modal" style={{ zIndex: 70, width: 460 }}>
        <div className="cp-drawer__header">
          <Icons.rotate size={14} />
          <div className="grow">
            <strong>{target === "shared" ? "Promote to shared" : "Demote to user"}</strong>{" "}
            <Mono dim style={{ marginLeft: 8, fontSize: 11 }}>{node.host_id}</Mono>
          </div>
          <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose}>
            <Icons.x size={14} />
          </button>
        </div>
        <div style={{ padding: 16 }}>
          {target === "shared" ? (
            <div className="vstack" style={{ gap: 6 }}>
              <span className="cp-label">New owner organization</span>
              <select className="cp-input" value={orgId} onChange={e => setOrgId(e.target.value)}>
                <option value="">— select an org —</option>
                {orgList.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              {orgList.length === 0 && (
                <span className="small dim">
                  No organizations exist. Create one in Admin → Organizations first.
                </span>
              )}
            </div>
          ) : (
            <div className="vstack" style={{ gap: 6 }}>
              <span className="cp-label">New owner user</span>
              <select className="cp-input" value={userId} onChange={e => setUserId(e.target.value)}>
                <option value="">— select a user —</option>
                {userList.map(u => <option key={u.id} value={u.id}>@{u.username}</option>)}
              </select>
            </div>
          )}
          {err && (
            <div className="small mono" style={{ color: "var(--err)", marginTop: 10 }}>{err}</div>
          )}
          <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
            <button type="button" className="cp-btn" onClick={onClose} disabled={update.isPending}>
              Cancel
            </button>
            <button type="button" className="cp-btn cp-btn--primary"
              disabled={update.isPending} onClick={submit}>
              <Icons.check size={12} />
              <span>{update.isPending ? "Saving…" : "Apply"}</span>
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function NodeLabelModal({ node, onClose }: { node: Node; onClose: () => void }) {
  const update = useUpdateNode();
  const [label, setLabel] = useState(node.label ?? "");
  const [err, setErr] = useState<string | null>(null);
  const submit = () => {
    setErr(null);
    update.mutate({ id: node.id, patch: { label: label.trim() || null } }, {
      onSuccess: onClose,
      onError: e => setErr(e instanceof Error ? e.message : String(e)),
    });
  };
  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onClose} />
      <div className="cp-modal" style={{ zIndex: 70, width: 420 }}>
        <div className="cp-drawer__header">
          <Icons.user size={14} />
          <div className="grow">
            <strong>Edit node label</strong>{" "}
            <Mono dim style={{ marginLeft: 8, fontSize: 11 }}>{node.host_id}</Mono>
          </div>
          <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose}>
            <Icons.x size={14} />
          </button>
        </div>
        <div style={{ padding: 16 }}>
          <div className="vstack" style={{ gap: 6 }}>
            <span className="cp-label">Label</span>
            <input className="cp-input cp-input--mono" value={label}
              autoFocus
              onChange={e => setLabel(e.target.value)}
              placeholder="(blank to clear)" />
          </div>
          {err && (
            <div className="small mono" style={{ color: "var(--err)", marginTop: 10 }}>{err}</div>
          )}
          <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
            <button type="button" className="cp-btn" onClick={onClose} disabled={update.isPending}>
              Cancel
            </button>
            <button type="button" className="cp-btn cp-btn--primary"
              disabled={update.isPending} onClick={submit}>
              <Icons.check size={12} />
              <span>{update.isPending ? "Saving…" : "Save"}</span>
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
