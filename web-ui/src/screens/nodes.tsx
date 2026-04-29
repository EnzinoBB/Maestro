import { useMemo, useState } from "react";
import { Mono, Pill, Icons, StatusDot, relTime, Sparkline } from "../primitives";
import { useHostCpuSeries, useNodes, type Node } from "../api/client";
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
    // Snapshot the host_ids that exist BEFORE opening, so the wizard can tell
    // when the freshly-enrolled host appears.
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
        {isAdmin && (
          <button type="button" className="cp-btn cp-btn--primary" onClick={openEnroll}>
            <Icons.plus size={12} />
            <span>Enroll new daemon</span>
          </button>
        )}
      </header>

      {isLoading && <div className="cp-skel" style={{ height: 120 }} />}
      {error && (
        <div className="cp-empty">
          <h2>Could not load nodes</h2>
          <p className="mono">{String(error)}</p>
        </div>
      )}

      {!isLoading && !error && nodes.length === 0 && (
        <NodesEmpty onEnroll={openEnroll} isAdmin={isAdmin} />
      )}

      {nodes.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))",
          gap: 12,
        }}>
          {nodes.map(n => <NodeCard key={n.id} node={n} />)}
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

function NodeCard({ node }: { node: Node }) {
  const display = node.label || node.host_id;
  const ownerLabel = node.node_type === "shared"
    ? `org ${node.owner_org_id}`
    : (node.owner_username ? `@${node.owner_username}` : node.owner_user_id);
  const ownerTitle = node.node_type === "shared"
    ? (node.owner_org_id ?? undefined)
    : (node.owner_user_id ?? undefined);
  return (
    <div className="cp-card" style={{ padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <StatusDot status={node.online ? "online" : "offline"} size={8} />
        <strong style={{ fontSize: 14 }}>{display}</strong>
        <div style={{ flex: 1 }} />
        <Pill status={node.node_type === "shared" ? "info" : "success"}>
          {node.node_type}
        </Pill>
      </div>
      <div className="small dim mono" style={{ marginBottom: 8 }}>
        host_id: {node.host_id} · owned by{" "}
        <span title={ownerTitle}>{ownerLabel}</span>
        {" "}· created {relTime(node.created_at)}
      </div>
      <NodeMiniMetrics hostId={node.host_id} online={node.online} />
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
