import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mono, Pill, Icons, StatusDot, relTime } from "../primitives";
import { useHostCpuSeries } from "../api/client";
import { Sparkline } from "../primitives";
import { useAuth } from "../hooks/useAuth";

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

type EnrollPayload = {
  cp_url: string;
  token: string;
  install_url: string;
  token_available: boolean;
};

async function fetchNodes(): Promise<{ nodes: Node[] }> {
  const r = await fetch("/api/nodes", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`nodes fetch failed: ${r.status}`);
  return r.json();
}

async function fetchEnroll(): Promise<EnrollPayload> {
  const r = await fetch("/api/admin/daemon-enroll", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`enroll fetch failed: ${r.status}`);
  return r.json();
}

export function NodesScreen() {
  const { state } = useAuth();
  const isAdmin = state.status === "single-user" || (state.status === "authenticated" && state.is_admin);
  const [enrollOpen, setEnrollOpen] = useState(false);
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
        <div style={{ flex: 1 }} />
        {isAdmin && (
          <button
            type="button"
            className="cp-btn cp-btn--primary"
            onClick={() => setEnrollOpen(o => !o)}
          >
            <Icons.plus size={12} />
            <span>{enrollOpen ? "Close" : "Enroll new daemon"}</span>
          </button>
        )}
      </header>

      {enrollOpen && <EnrollWizard onClose={() => setEnrollOpen(false)} />}

      {isLoading && <div className="cp-skel" style={{ height: 120 }} />}
      {error && (
        <div className="cp-empty">
          <h2>Could not load nodes</h2>
          <p className="mono">{String(error)}</p>
        </div>
      )}
      {!isLoading && !error && nodes.length === 0 && !enrollOpen && (
        <div className="cp-empty">
          <h2>No nodes registered yet</h2>
          <p>Run the daemon installer on a target host and it will auto-register.</p>
          {isAdmin && (
            <button
              type="button"
              className="cp-btn cp-btn--primary"
              style={{ marginTop: 10 }}
              onClick={() => setEnrollOpen(true)}
            >
              <Icons.plus size={12} />
              <span>Show enroll command</span>
            </button>
          )}
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

function EnrollWizard({ onClose }: { onClose: () => void }) {
  const [hostId, setHostId] = useState("");
  const [copied, setCopied] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["daemon-enroll"],
    queryFn: fetchEnroll,
    refetchOnMount: "always",
  });

  const command = data ? buildCommand(data, hostId) : "";

  const onCopy = async () => {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked — fall back to manual select; we can't help further here
    }
  };

  return (
    <div className="cp-card" style={{ marginBottom: 16, padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <Icons.plus size={14} />
        <strong>Enroll a new daemon</strong>
        <div style={{ flex: 1 }} />
        <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm" onClick={onClose} title="Close">
          <Icons.x size={12} />
        </button>
      </div>

      {isLoading && <div className="cp-skel" style={{ height: 160 }} />}
      {error && (
        <div className="small mono" style={{ color: "var(--err)" }}>
          {String(error)} — only admins can fetch enroll details.
        </div>
      )}

      {data && (
        <>
          {!data.token_available && (
            <div className="cp-banner" style={{ marginBottom: 12 }}>
              <span className="cp-banner__dot" />
              <div className="small">
                <strong>Daemon token not found.</strong>{" "}
                The CP container hasn't generated its token yet, or it's stored at an unexpected path.
                Set <Mono>MAESTRO_DAEMON_TOKEN</Mono> in the compose env, or check the container logs
                for "GENERATED MAESTRO DAEMON TOKEN".
              </div>
            </div>
          )}

          <div style={{ maxWidth: 640, marginBottom: 14 }}>
            <div className="cp-label">Host ID for the new daemon</div>
            <input
              className="cp-input cp-input--mono"
              placeholder="e.g. api-01, web-eu-3, db-replica"
              value={hostId}
              onChange={e => setHostId(e.target.value.replace(/\s+/g, ""))}
              autoFocus
            />
            <div className="small dim" style={{ marginTop: 4 }}>
              Identifier for the new node (defaults to <Mono>hostname -s</Mono> on the target if left empty).
              Pick something stable and unique within this CP.
            </div>
          </div>

          <div className="cp-label" style={{ marginBottom: 4 }}>
            Run this on the target host (Linux/macOS) as root:
          </div>
          <pre className="cp-yaml" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }} data-testid="enroll-command">{command}</pre>
          <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center" }}>
            <button
              type="button"
              className="cp-btn cp-btn--primary"
              onClick={onCopy}
              disabled={!data.token_available}
            >
              <Icons.check size={12} />
              <span>{copied ? "Copied!" : "Copy command"}</span>
            </button>
            <span className="small dim">
              CP URL: <Mono>{data.cp_url}</Mono>
            </span>
          </div>

          <div className="small dim" style={{ marginTop: 16, lineHeight: 1.5 }}>
            <strong>What this does</strong>: downloads the latest <Mono>install-daemon.sh</Mono>,
            installs the <Mono>maestrod</Mono> binary at <Mono>/usr/local/bin/maestrod</Mono>,
            writes a systemd (or launchd on macOS) service unit, and starts it. The daemon
            connects back here over WebSocket and shows up in the list above within a few seconds.
            <br />
            <strong>Tips</strong>: pass <Mono>--auto-update</Mono> to install a weekly upgrade timer;
            pass <Mono>--insecure</Mono> if your CP URL is plain HTTP (not recommended for production).
          </div>
        </>
      )}
    </div>
  );
}

function buildCommand(p: EnrollPayload, hostId: string): string {
  const lines = [
    `curl -fsSL ${p.install_url} \\`,
    `  | sudo bash -s -- \\`,
    `      --cp-url ${p.cp_url} \\`,
    `      --token ${p.token || "<TOKEN_MISSING>"}`,
  ];
  if (hostId.trim()) {
    lines[lines.length - 1] += " \\";
    lines.push(`      --host-id ${hostId.trim()}`);
  }
  return lines.join("\n");
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
