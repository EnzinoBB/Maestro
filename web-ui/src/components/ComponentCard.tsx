import { Link } from "react-router-dom";
import { Pill, Mono, Sparkline } from "../primitives";
import { useComponentMetric, type ComponentState } from "../api/client";
import type { ParsedComponent } from "../lib/yamlparse";

function statusKey(states: ComponentState[]): string {
  if (states.length === 0) return "unknown";
  const has = (s: string) => states.some(x => (x.status || "").toLowerCase() === s);
  if (has("unhealthy") || has("failed")) return "failed";
  if (has("stopped") || has("host_offline") || has("offline")) return "offline";
  if (has("running") || has("healthy")) return "healthy";
  return "unknown";
}

function statusLabel(states: ComponentState[]): string {
  if (states.length === 0) return "no state";
  const norm = (x: ComponentState) => (x.status || "unknown").toLowerCase();
  const worst =
    states.find(s => ["unhealthy", "failed"].includes(norm(s))) ??
    states.find(s => ["stopped", "host_offline", "offline"].includes(norm(s))) ??
    states[0];
  return worst.status || "unknown";
}

function sourceSummary(c: ParsedComponent): string {
  const s = c.source;
  if (s.type === "docker") return s.tag ? `${s.image}:${s.tag}` : s.image;
  if (s.type === "git") return s.ref ? `${s.repo}@${s.ref}` : s.repo;
  if (s.type === "archive") return s.path;
  return "unknown source";
}

export function ComponentCard({
  component,
  states,
}: {
  component: ParsedComponent;
  states: ComponentState[];
}) {
  const cpu = useComponentMetric(component.id, "container_cpu_percent");
  const ram = useComponentMetric(component.id, "container_ram_percent");
  const cpuSeries = (cpu.data || []).map(([t, v]) => ({ t, v }));
  const ramSeries = (ram.data || []).map(([t, v]) => ({ t, v }));
  const cpuLast = cpuSeries.length ? cpuSeries[cpuSeries.length - 1].v : null;
  const ramLast = ramSeries.length ? ramSeries[ramSeries.length - 1].v : null;
  const sk = statusKey(states);

  return (
    <div className="cp-card cp-component-card">
      <div className="cp-component-card__head">
        <Mono style={{ fontWeight: 600 }}>{component.id}</Mono>
        <div style={{ flex: 1 }} />
        <Pill status={sk}>{statusLabel(states)}</Pill>
      </div>

      <div className="small dim mono cp-component-card__src">{sourceSummary(component)}</div>

      <div className="small dim cp-component-card__hosts">
        {component.hosts.length === 0 ? "no host binding" : `on ${component.hosts.join(", ")}`}
      </div>

      <div className="cp-component-card__metric">
        <span className="small dim">CPU</span>
        <Mono style={{ fontSize: 12 }}>{cpuLast == null ? "—" : `${cpuLast.toFixed(1)}%`}</Mono>
        {cpuSeries.length > 0 && <Sparkline data={cpuSeries} width={140} height={22} />}
      </div>
      <div className="cp-component-card__metric">
        <span className="small dim">RAM</span>
        <Mono style={{ fontSize: 12 }}>{ramLast == null ? "—" : `${ramLast.toFixed(1)}%`}</Mono>
        {ramSeries.length > 0 && <Sparkline data={ramSeries} width={140} height={22} />}
      </div>

      <div className="cp-component-card__footer">
        <Link to={`/components/${encodeURIComponent(component.id)}/logs`} className="cp-link small">
          View logs →
        </Link>
        {/* Phase 3 attaches per-component action buttons (Rollback / Tests /
            Remove / Update) here. Grep marker: cp-component-card__actions */}
        <div className="cp-component-card__actions" />
      </div>
    </div>
  );
}
