import { useParams } from "react-router-dom";
import { useDeploy, useRollback, deployHealth } from "../api/client";
import { Pill, Mono, relTime, Icons, StatusDot } from "../primitives";

export function DeployDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useDeploy(id);
  const rollback = useRollback();

  if (isLoading) return <div className="cp-page"><div className="cp-skel" style={{ height: 120 }} /></div>;
  if (error) return <div className="cp-page"><div className="cp-empty"><h2>Error</h2><p className="mono">{String(error)}</p></div></div>;
  if (!data) return null;

  const health = deployHealth(data, data.versions);

  return (
    <div>
      <div className="cp-page" style={{ paddingBottom: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <StatusDot status={health.status} size={10} />
          <h1>{data.name}</h1>
          <Pill status={health.status}>{health.label}</Pill>
          <div style={{ flex: 1 }} />
          <Mono dim>v{data.current_version ?? "—"}</Mono>
        </div>
        <div className="small dim mono" style={{ marginBottom: 16 }}>
          {data.id} · owned by {data.owner_user_id} · created {relTime(data.created_at)}
        </div>
      </div>

      <div className="cp-tabs">
        <span className="cp-tab active">Versions</span>
        <span className="cp-tab">Components <span className="dim small">(M2)</span></span>
        <span className="cp-tab">Configuration <span className="dim small">(soon)</span></span>
        <span className="cp-tab">Metrics <span className="dim small">(M2)</span></span>
      </div>

      <div className="cp-page">
        {data.versions.length === 0 ? (
          <div className="cp-empty">
            <h2>No versions yet</h2>
            <p>This deploy has no applied versions. Use the Wizard or POST to <Mono>/api/deploys/{data.id}/apply</Mono>.</p>
          </div>
        ) : (
          <ol className="cp-timeline" style={{ listStyle: "none", paddingLeft: 20 }}>
            {[...data.versions].reverse().map(v => {
              const isCurrent = v.version_n === data.current_version;
              const ok = v.result_json?.ok;
              const status: "success" | "failed" | "in-progress" =
                ok === true ? "success" : ok === false ? "failed" : "in-progress";
              return (
                <li key={v.id} className="cp-timeline__item">
                  <span className="cp-timeline__dot" style={{ borderColor: isCurrent ? "var(--accent)" : undefined }} />
                  <div style={{ display: "flex", gap: 14, alignItems: "baseline", flexWrap: "wrap" }}>
                    <Mono style={{ fontSize: 13, fontWeight: 600 }}>v{v.version_n}</Mono>
                    <Pill status={status}>{ok === true ? "Success" : ok === false ? "Failed" : "Unknown"}</Pill>
                    {v.kind === "rollback" && <span className="cp-badge"><Icons.rotate size={10} /> rollback</span>}
                    {isCurrent && <span className="cp-badge" style={{ color: "var(--accent)", borderColor: "var(--accent)" }}>current</span>}
                    <span className="small dim">{relTime(v.applied_at)}</span>
                    <span className="small dim mono">by {v.applied_by_user_id}</span>
                    {!isCurrent && (
                      <button
                        type="button"
                        className="cp-btn cp-btn--sm"
                        onClick={() => id && rollback.mutate({ deployId: id, versionN: v.version_n })}
                        disabled={rollback.isPending}
                      >
                        <Icons.rotate size={11} />
                        <span>Rollback here</span>
                      </button>
                    )}
                  </div>
                  {v.result_json?.error && (
                    <div className="small mono" style={{ color: "var(--err)", marginTop: 4 }}>
                      {v.result_json.error}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
