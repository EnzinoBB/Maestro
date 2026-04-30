import { Link, useParams } from "react-router-dom";
import { useComponentLogs } from "../api/client";
import { Mono } from "../primitives";

export function ComponentLogsScreen() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useComponentLogs(id);

  if (!id) return null;
  return (
    <div className="cp-page">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <h1>Logs</h1>
        <Mono dim>{id}</Mono>
        <div style={{ flex: 1 }} />
        <Link to="/" className="cp-link small">← back</Link>
      </div>
      <p className="small dim">
        Last 200 lines, refreshed every 5s. Streaming arrives in Phase 3 (§G <Mono>tail_logs_stream</Mono>).
      </p>
      {isLoading && <div className="cp-skel" style={{ height: 120 }} />}
      {error && (
        <pre className="cp-pre" style={{ color: "var(--err)" }}>
          {String(error)}
        </pre>
      )}
      {data && (
        <pre className="cp-pre">{(data.lines || []).join("\n")}</pre>
      )}
    </div>
  );
}
