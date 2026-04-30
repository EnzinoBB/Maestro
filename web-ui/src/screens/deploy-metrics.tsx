import { Link, useParams } from "react-router-dom";
import { useDeploy, useMetricRange, useComponentMetric } from "../api/client";
import { AreaChart, Mono } from "../primitives";
import { parseDeployYaml } from "../lib/yamlparse";

export function DeployMetricsScreen() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useDeploy(id);

  if (isLoading) return <div className="cp-page"><div className="cp-skel" style={{ height: 200 }} /></div>;
  if (!data) return null;
  const currentVersion = data.versions.find(v => v.version_n === data.current_version);
  const parsed = currentVersion
    ? parseDeployYaml(currentVersion.yaml_text)
    : { hosts: [], components: [] };
  const hostIds = parsed.hosts;
  const compIds = parsed.components.map(c => c.id);

  return (
    <div className="cp-page">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <Link to={`/deploys/${id}`} className="cp-btn cp-btn--sm cp-btn--ghost">
          <span>← Back to deploy</span>
        </Link>
        <h1>{data.name} — metrics</h1>
      </div>
      <div className="small dim mono" style={{ marginBottom: 20 }}>
        last 15 minutes · refreshes every 10s · live updates on WS events
      </div>

      {hostIds.length === 0 && compIds.length === 0 && (
        <div className="cp-empty"><h2>No targets in this deploy</h2></div>
      )}

      {hostIds.length > 0 && (
        <section style={{ marginBottom: 32 }}>
          <div className="cp-section-title" style={{ marginBottom: 12 }}>Hosts</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {hostIds.map(h => (
              <div key={`${h}-cpu`} className="cp-card" style={{ padding: 14 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 8 }}>
                  <Mono>{h}</Mono>
                  <span className="small dim">host CPU %</span>
                </div>
                <HostCpuPanel hostId={h} />
              </div>
            ))}
            {hostIds.map(h => (
              <div key={`${h}-ram`} className="cp-card" style={{ padding: 14 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 8 }}>
                  <Mono>{h}</Mono>
                  <span className="small dim">host RAM %</span>
                </div>
                <HostRamPanel hostId={h} />
              </div>
            ))}
          </div>
        </section>
      )}

      {compIds.length > 0 && (
        <section>
          <div className="cp-section-title" style={{ marginBottom: 12 }}>Components</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {compIds.map(c => (
              <div key={`${c}-cpu`} className="cp-card" style={{ padding: 14 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 8 }}>
                  <Mono>{c}</Mono>
                  <span className="small dim">container CPU %</span>
                </div>
                <ComponentMetricPanel componentId={c} metric="container_cpu_percent" />
              </div>
            ))}
            {compIds.map(c => (
              <div key={`${c}-ram`} className="cp-card" style={{ padding: 14 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 8 }}>
                  <Mono>{c}</Mono>
                  <span className="small dim">container RAM %</span>
                </div>
                <ComponentMetricPanel componentId={c} metric="container_ram_percent" />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function seriesOrEmpty(data: [number, number][] | undefined) {
  return (data || []).map(([t, v]) => ({ t, v }));
}

function HostCpuPanel({ hostId }: { hostId: string }) {
  const { data, isLoading } = useMetricRange("host", hostId, "cpu_percent", 15 * 60);
  return <MetricAreaChartShell loading={isLoading} series={seriesOrEmpty(data)} />;
}
function HostRamPanel({ hostId }: { hostId: string }) {
  const { data, isLoading } = useMetricRange("host", hostId, "ram_percent", 15 * 60);
  return <MetricAreaChartShell loading={isLoading} series={seriesOrEmpty(data)} />;
}
function ComponentMetricPanel({ componentId, metric }: { componentId: string; metric: string }) {
  const { data, isLoading } = useComponentMetric(componentId, metric, 15 * 60);
  return <MetricAreaChartShell loading={isLoading} series={seriesOrEmpty(data)} />;
}

function MetricAreaChartShell({ loading, series }: {
  loading: boolean; series: { t: number; v: number }[];
}) {
  if (loading) return <div className="cp-skel" style={{ height: 180 }} />;
  if (series.length === 0) return <div className="small dim" style={{ padding: 24 }}>no samples in window</div>;
  return <AreaChart data={series} height={180} />;
}
