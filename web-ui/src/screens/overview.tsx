import { useState } from "react";
import { Link } from "react-router-dom";
import { useDeploys, useCreateDeploy, deployHealth, type Deploy } from "../api/client";
import { Pill, Icons, Mono, relTime, StatusDot } from "../primitives";

export function OverviewScreen() {
  const { data, isLoading, error } = useDeploys();
  const create = useCreateDeploy();
  const [newName, setNewName] = useState("");
  const deploys = data?.deploys ?? [];

  const totals = {
    deploys: deploys.length,
    withVersion: deploys.filter(d => d.current_version != null).length,
  };

  return (
    <div className="cp-page">
      <header style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 16 }}>
        <h1>Overview</h1>
        <span className="small dim mono">{totals.deploys} deploys · {totals.withVersion} applied</span>
      </header>

      <section className="cp-stats" style={{ marginBottom: 20 }}>
        <div className="cp-stat">
          <div className="cp-stat__label"><Icons.deploy size={12} /> Deploys</div>
          <div className="cp-stat__value">{totals.deploys}</div>
          <div className="cp-stat__meta">{totals.withVersion} applied · {totals.deploys - totals.withVersion} empty</div>
        </div>
        <div className="cp-stat">
          <div className="cp-stat__label"><Icons.alert size={12} /> Alerts</div>
          <div className="cp-stat__value">—</div>
          <div className="cp-stat__meta">metrics pending (M2)</div>
        </div>
        <div className="cp-stat">
          <div className="cp-stat__label"><Icons.node size={12} /> Nodes</div>
          <div className="cp-stat__value">—</div>
          <div className="cp-stat__meta">/api/nodes not yet wired</div>
        </div>
        <div className="cp-stat">
          <div className="cp-stat__label"><Icons.check size={12} /> Components healthy</div>
          <div className="cp-stat__value">—</div>
          <div className="cp-stat__meta">awaiting daemon metrics</div>
        </div>
      </section>

      <section style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 10 }}>
        <h2 style={{ flex: 1 }}>Your deploys</h2>
        <form
          onSubmit={e => {
            e.preventDefault();
            if (!newName.trim()) return;
            create.mutate(newName.trim(), {
              onSuccess: () => setNewName(""),
            });
          }}
          style={{ display: "flex", gap: 6 }}
        >
          <input
            className="cp-input cp-input--mono"
            style={{ width: 220 }}
            placeholder="new deploy name…"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            disabled={create.isPending}
          />
          <button type="submit" className="cp-btn cp-btn--primary" disabled={!newName.trim() || create.isPending}>
            <Icons.plus size={12} />
            <span>Create</span>
          </button>
        </form>
      </section>

      {isLoading && <div className="cp-skel" style={{ height: 120 }} />}
      {error && (
        <div className="cp-empty">
          <h2>Could not reach the control plane</h2>
          <p className="mono">{String(error)}</p>
        </div>
      )}
      {!isLoading && !error && deploys.length === 0 && (
        <div className="cp-empty">
          <h2>No deploys yet</h2>
          <p>Create your first deploy above, or open the Wizard for a guided flow.</p>
          <Link to="/wizard" className="cp-btn cp-btn--primary" style={{ display: "inline-flex" }}>
            <Icons.wizard size={12} /> Open Wizard
          </Link>
        </div>
      )}

      {deploys.length > 0 && (
        <div className="cp-deploy-grid">
          {deploys.map(d => <DeployCard key={d.id} deploy={d} />)}
        </div>
      )}
    </div>
  );
}

function DeployCard({ deploy }: { deploy: Deploy }) {
  const health = deployHealth(deploy);
  return (
    <Link to={`/deploys/${deploy.id}`} className="cp-deploy-card" style={{ textDecoration: "none", color: "inherit", display: "block" }}>
      <div className="cp-deploy-card__row">
        <div className="cp-deploy-card__name">
          <StatusDot status={health.status} size={8} />
          {deploy.name}
        </div>
        <Pill status={health.status}>{health.label}</Pill>
      </div>
      <div className="cp-deploy-card__meta">
        <span><Mono dim>v{deploy.current_version ?? "—"}</Mono></span>
        <span>updated {relTime(deploy.updated_at)}</span>
        <span><Mono dim>{deploy.owner_user_id}</Mono></span>
      </div>
      <div className="cp-deploy-card__actions">
        <span className="cp-btn cp-btn--sm">
          <Icons.deploy size={11} />
          <span>Open</span>
        </span>
      </div>
    </Link>
  );
}
