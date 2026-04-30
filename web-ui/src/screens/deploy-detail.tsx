import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  useDeploy,
  useRollback,
  deployHealth,
  useHostCpuSeries,
  useDeployState,
  type DeployWithVersions,
  type ComponentState,
} from "../api/client";
import { Pill, Mono, relTime, Icons, StatusDot, Sparkline } from "../primitives";
import { parseDeployYaml, type ParsedDeployment } from "../lib/yamlparse";
import { ComponentCard } from "../components/ComponentCard";

type TabKey = "versions" | "components" | "configuration";

export function DeployDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useDeploy(id);
  const rollback = useRollback();
  const [search, setSearch] = useSearchParams();
  const tab = (search.get("tab") as TabKey) || "versions";
  const setTab = (t: TabKey) => {
    const next = new URLSearchParams(search);
    if (t === "versions") next.delete("tab");
    else next.set("tab", t);
    setSearch(next, { replace: true });
  };

  if (isLoading) return <div className="cp-page"><div className="cp-skel" style={{ height: 120 }} /></div>;
  if (error) return <div className="cp-page"><div className="cp-empty"><h2>Error</h2><p className="mono">{String(error)}</p></div></div>;
  if (!data) return null;

  const health = deployHealth(data);
  const currentVersion = data.versions.find(v => v.version_n === data.current_version);
  const parsed: ParsedDeployment = currentVersion
    ? parseDeployYaml(currentVersion.yaml_text)
    : { hosts: [], components: [] };
  const hostIds = parsed.hosts;

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
          {data.id} · owned by{" "}
          <span title={data.owner_user_id}>
            {data.owner_username ? `@${data.owner_username}` : data.owner_user_id}
          </span>
          {" "}· created {relTime(data.created_at)}
        </div>
      </div>

      <div className="cp-tabs">
        <button
          type="button"
          className={`cp-tab${tab === "versions" ? " active" : ""}`}
          onClick={() => setTab("versions")}
        >
          Versions
        </button>
        <button
          type="button"
          className={`cp-tab${tab === "components" ? " active" : ""}`}
          onClick={() => setTab("components")}
        >
          Components
        </button>
        <button
          type="button"
          className={`cp-tab${tab === "configuration" ? " active" : ""}`}
          onClick={() => setTab("configuration")}
        >
          Configuration
        </button>
        <Link to={`/deploys/${id}/metrics`} className="cp-tab">Metrics</Link>
      </div>

      {tab === "versions" && (
        <div className="cp-page">
          {hostIds.length > 0 && (
            <section style={{ marginBottom: 24 }}>
              <div className="cp-section-title" style={{ marginBottom: 10 }}>
                Hosts ({hostIds.length}) — host CPU over last 15 minutes
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
                {hostIds.map(h => <HostMetricsCard key={h} hostId={h} />)}
              </div>
            </section>
          )}

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
                      <span className="small dim mono" title={v.applied_by_user_id}>
                        by {v.applied_by_username ? `@${v.applied_by_username}` : v.applied_by_user_id}
                      </span>
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
      )}

      {tab === "components" && id && (
        <ComponentsTab parsed={parsed} deployId={id} />
      )}

      {tab === "configuration" && id && (
        <ConfigurationTab data={data} deployId={id} />
      )}
    </div>
  );
}

function HostMetricsCard({ hostId }: { hostId: string }) {
  const { data, isLoading } = useHostCpuSeries(hostId, 15 * 60);
  const series = (data || []).map(([t, v]) => ({ t, v }));
  const last = series.length > 0 ? series[series.length - 1].v : null;
  return (
    <div className="cp-card" style={{ padding: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <Mono>{hostId}</Mono>
        <div style={{ flex: 1 }} />
        <span className="small dim">CPU</span>
        <Mono style={{ fontSize: 12 }}>{last == null ? "—" : `${last.toFixed(1)}%`}</Mono>
      </div>
      {isLoading ? (
        <div className="cp-skel" style={{ height: 30 }} />
      ) : series.length > 0 ? (
        <Sparkline data={series} width={220} height={30} />
      ) : (
        <div className="small dim">no samples in window</div>
      )}
    </div>
  );
}

function ComponentsTab({ parsed, deployId }: { parsed: ParsedDeployment; deployId: string }) {
  const state = useDeployState();
  if (parsed.components.length === 0) {
    return <div className="cp-page"><div className="cp-empty"><p>No components in current version YAML.</p></div></div>;
  }
  const byCid = new Map<string, ComponentState[]>();
  for (const cs of state.data?.components || []) {
    const id = cs.component_id;
    if (!byCid.has(id)) byCid.set(id, []);
    byCid.get(id)!.push(cs);
  }
  void deployId; // reserved for Phase 3 per-deploy state endpoint.
  return (
    <div className="cp-page">
      <div className="cp-component-grid">
        {parsed.components.map(c => (
          <ComponentCard key={c.id} component={c} states={byCid.get(c.id) || []} />
        ))}
      </div>
    </div>
  );
}

function ConfigurationTab(_p: { data: DeployWithVersions; deployId: string }) {
  return <div className="cp-page"><div className="cp-empty"><p>Configuration — wiring up…</p></div></div>;
}
