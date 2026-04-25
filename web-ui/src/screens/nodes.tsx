import { useQuery } from "@tanstack/react-query";
import { Mono, Pill, Icons, StatusDot, relTime } from "../primitives";
import { useHostCpuSeries } from "../api/client";
import { Sparkline } from "../primitives";

type Node = {
  id: string;
  host_id: string;
  node_type: "user" | "shared";
  owner_user_id: string | null;
  owner_org_id: string | null;
  label: string | null;
  created_at: number;
  online: boolean;
};

async function fetchNodes(): Promise<{ nodes: Node[] }> {
  const r = await fetch("/api/nodes", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`nodes fetch failed: ${r.status}`);
  return r.json();
}

export function NodesScreen() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["nodes"],
    queryFn: fetchNodes,
    refetchInterval: 5000,
  });
  const nodes = data?.nodes ?? [];

  return (
    <div className="cp-page">
      <header style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 16 }}>
        <h1>Nodes</h1>
        <span className="small dim mono">{nodes.length} total · {nodes.filter(n => n.online).length} online</span>
      </header>

      {isLoading && <div className="cp-skel" style={{ height: 120 }} />}
      {error && (
        <div className="cp-empty">
          <h2>Could not load nodes</h2>
          <p className="mono">{String(error)}</p>
        </div>
      )}
      {!isLoading && !error && nodes.length === 0 && (
        <div className="cp-empty">
          <h2>No nodes registered yet</h2>
          <p>Connect a daemon and it will auto-register here. Until then there's nothing to manage.</p>
        </div>
      )}

      {nodes.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))", gap: 12 }}>
          {nodes.map(n => <NodeCard key={n.id} node={n} />)}
        </div>
      )}
    </div>
  );
}

function NodeCard({ node }: { node: Node }) {
  const display = node.label || node.host_id;
  const owner = node.node_type === "shared"
    ? `org ${node.owner_org_id}`
    : node.owner_user_id;
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
        host_id: {node.host_id} · owned by {owner} · created {relTime(node.created_at)}
      </div>
      <NodeMiniMetrics hostId={node.host_id} online={node.online} />
    </div>
  );
}

function NodeMiniMetrics({ hostId, online }: { hostId: string; online: boolean }) {
  const { data } = useHostCpuSeries(hostId, 15 * 60, online);
  const series = (data || []).map(([t, v]) => ({ t, v }));
  if (!online) {
    return <div className="small dim" style={{ height: 30, display: "flex", alignItems: "center" }}>
      <Icons.alert size={11} /> &nbsp; daemon offline
    </div>;
  }
  if (series.length === 0) {
    return <div className="small dim" style={{ height: 30, display: "flex", alignItems: "center" }}>
      no samples in window
    </div>;
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
