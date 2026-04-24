import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { postDockerInspect, useCreateDeploy } from "../api/client";
import { Icons, Mono } from "../primitives";
import { initialWizardState, defaultComponentId, type WizardState } from "../wizard/types";
import { generateYaml } from "../wizard/yamlgen";

type StepId = "intent" | "source" | "source-details" | "placement" | "runtime" | "review";
const STEPS: { id: StepId; label: string }[] = [
  { id: "intent", label: "Intent" },
  { id: "source", label: "Source" },
  { id: "source-details", label: "Source details" },
  { id: "placement", label: "Placement" },
  { id: "runtime", label: "Runtime" },
  { id: "review", label: "Review" },
];

export function WizardScreen() {
  const [state, setState] = useState<WizardState>(initialWizardState);
  const [step, setStep] = useState<StepId>("intent");
  const stepIdx = STEPS.findIndex(s => s.id === step);
  const update = (patch: Partial<WizardState>) => setState(s => ({ ...s, ...patch }));

  const canGoNext = useMemo(() => validateStep(state, step), [state, step]);
  const next = () => { if (stepIdx < STEPS.length - 1) setStep(STEPS[stepIdx + 1].id); };
  const prev = () => { if (stepIdx > 0) setStep(STEPS[stepIdx - 1].id); };

  return (
    <div className="cp-wiz">
      <aside className="cp-wiz__steps">
        {STEPS.map((s, i) => {
          const done = i < stepIdx;
          const active = s.id === step;
          return (
            <div key={s.id} className={`cp-wiz__step${active ? " active" : ""}${done ? " done" : ""}`} onClick={() => {
              if (i <= stepIdx) setStep(s.id);
            }}>
              <span className="cp-wiz__step-num">{done ? "✓" : i + 1}</span>
              <div>
                <div className="cp-wiz__step-label">{s.label}</div>
                <div className="cp-wiz__step-sub">{summarizeStep(s.id, state)}</div>
              </div>
            </div>
          );
        })}
      </aside>
      <div className="cp-wiz__body">
        {step === "intent" && <IntentStep />}
        {step === "source" && <SourceStep />}
        {step === "source-details" && <SourceDetailsStep state={state} update={update} />}
        {step === "placement" && <PlacementStep state={state} update={update} />}
        {step === "runtime" && <RuntimeStep state={state} update={update} />}
        {step === "review" && <ReviewStep state={state} />}
        <div className="cp-wiz__footer">
          <button type="button" className="cp-btn" onClick={prev} disabled={stepIdx === 0}>
            Back
          </button>
          {step !== "review" ? (
            <button type="button" className="cp-btn cp-btn--primary" onClick={next} disabled={!canGoNext}>
              Next
              <Icons.apply size={12} />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function validateStep(s: WizardState, id: StepId): boolean {
  switch (id) {
    case "intent": return s.entryPoint === "new";
    case "source": return s.sourceType === "docker";
    case "source-details": return !!s.image && !!s.tag && !!s.componentId;
    case "placement": return s.deployName.length > 0 && s.hostIds.length > 0;
    case "runtime": return s.healthcheck.type === "none" || !!s.healthcheck.url;
    case "review": return true;
  }
}

function summarizeStep(id: StepId, s: WizardState): string {
  switch (id) {
    case "intent": return "create a new deploy";
    case "source": return s.sourceType;
    case "source-details": return s.image ? `${s.image}:${s.tag}` : "pick an image";
    case "placement": return s.hostIds.length ? `${s.hostIds.length} host(s) · ${s.deployName || "(name?)"}` : "pick hosts";
    case "runtime": return `${s.env.length} env · ${s.ports.length} ports · ${s.volumes.length} volumes`;
    case "review": return "generated YAML";
  }
}

function IntentStep() {
  return (
    <section>
      <h1>What do you want to do?</h1>
      <p className="dim">M3 ships the "new deploy" entry point. Add-component and upgrade-component arrive in M3.5.</p>
      <div className="cp-radio-cards" style={{ marginTop: 16 }}>
        <div className="cp-radio-card selected">
          <div className="cp-radio-card__icon"><Icons.plus size={18} /></div>
          <div><strong>New deploy</strong></div>
          <div className="small dim">Scaffold a fresh deploy from a Docker image.</div>
        </div>
      </div>
    </section>
  );
}

function SourceStep() {
  return (
    <section>
      <h1>Where does the code come from?</h1>
      <p className="dim">M3 covers Docker only. Git and Archive arrive in M3.5.</p>
      <div className="cp-radio-cards" style={{ marginTop: 16 }}>
        <div className="cp-radio-card selected">
          <div className="cp-radio-card__icon"><Icons.deploy size={18} /></div>
          <div><strong>Docker image</strong></div>
          <div className="small dim">Inspect metadata and suggest ports / volumes / env.</div>
        </div>
      </div>
    </section>
  );
}

type StepProps = { state: WizardState; update: (p: Partial<WizardState>) => void };

function SourceDetailsStep({ state, update }: StepProps) {
  const [inspecting, setInspecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onInspect = async () => {
    setInspecting(true); setError(null);
    try {
      const s = await postDockerInspect(state.image, state.tag);
      update({
        ports: state.ports.length ? state.ports : s.exposed_ports.map(p => `${p}:${p}`),
        volumes: state.volumes.length ? state.volumes : s.volumes.map(v => `/maestro-data${v}:${v}`),
        env: state.env.length ? state.env : s.env.slice(0, 10),
        componentId: state.componentId || defaultComponentId(state.image),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInspecting(false);
    }
  };

  return (
    <section>
      <h1>Docker image</h1>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 140px", gap: 12, maxWidth: 640 }}>
        <label>
          <div className="cp-label">Image</div>
          <input className="cp-input cp-input--mono" placeholder="nginx"
            value={state.image} onChange={e => update({ image: e.target.value })} />
        </label>
        <label>
          <div className="cp-label">Tag</div>
          <input className="cp-input cp-input--mono" placeholder="1.25"
            value={state.tag} onChange={e => update({ tag: e.target.value })} />
        </label>
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" className="cp-btn" onClick={onInspect}
          disabled={!state.image || inspecting}>
          {inspecting ? "Inspecting…" : "Inspect image"}
        </button>
        {error && <span className="small" style={{ color: "var(--err)" }}>{error}</span>}
      </div>

      <div style={{ marginTop: 20, maxWidth: 640 }}>
        <div className="cp-label">Component ID</div>
        <input className="cp-input cp-input--mono"
          value={state.componentId}
          placeholder={defaultComponentId(state.image)}
          onChange={e => update({ componentId: e.target.value })} />
        <div className="small dim" style={{ marginTop: 4 }}>
          Identifies this component inside the deploy. Defaults to the image's last path segment.
        </div>
      </div>
    </section>
  );
}

function PlacementStep({ state, update }: StepProps) {
  const [hostInput, setHostInput] = useState("");
  const addHost = () => {
    const h = hostInput.trim();
    if (!h || state.hostIds.includes(h)) return;
    update({ hostIds: [...state.hostIds, h] });
    setHostInput("");
  };
  return (
    <section>
      <h1>Placement</h1>
      <div style={{ maxWidth: 640 }}>
        <div className="cp-label">Deploy name</div>
        <input className="cp-input cp-input--mono" placeholder="webapp-prod"
          value={state.deployName} onChange={e => update({ deployName: e.target.value })} />
      </div>
      <div style={{ marginTop: 18, maxWidth: 640 }}>
        <div className="cp-label">Hosts</div>
        <div style={{ display: "flex", gap: 6 }}>
          <input className="cp-input cp-input--mono" placeholder="host1"
            value={hostInput} onChange={e => setHostInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addHost(); } }} />
          <button type="button" className="cp-btn" onClick={addHost}>Add</button>
        </div>
        <div className="cp-chips" style={{ marginTop: 8 }}>
          {state.hostIds.map(h => (
            <span key={h} className="cp-chip">
              {h}
              <button type="button" onClick={() => update({ hostIds: state.hostIds.filter(x => x !== h) })}>×</button>
            </span>
          ))}
          {state.hostIds.length === 0 && <span className="small dim">no hosts yet</span>}
        </div>
      </div>
      <div style={{ marginTop: 18, maxWidth: 640 }}>
        <div className="cp-label">Strategy</div>
        <select className="cp-select" value={state.strategy}
          onChange={e => update({ strategy: e.target.value as WizardState["strategy"] })}>
          <option value="sequential">sequential</option>
          <option value="parallel">parallel</option>
          <option value="canary">canary</option>
        </select>
      </div>
    </section>
  );
}

function RuntimeStep({ state, update }: StepProps) {
  const [portInput, setPortInput] = useState("");
  const [volInput, setVolInput] = useState("");
  const updateEnv = (i: number, patch: Partial<{ key: string; value: string }>) => {
    const next = state.env.slice();
    next[i] = { ...next[i], ...patch };
    update({ env: next });
  };
  return (
    <section>
      <h1>Runtime</h1>

      <div style={{ maxWidth: 640, marginTop: 8 }}>
        <div className="cp-label">Ports (HOST:CONTAINER)</div>
        <div style={{ display: "flex", gap: 6 }}>
          <input className="cp-input cp-input--mono" placeholder="80:80"
            value={portInput} onChange={e => setPortInput(e.target.value)} />
          <button type="button" className="cp-btn" onClick={() => {
            const p = portInput.trim();
            if (p && !state.ports.includes(p)) update({ ports: [...state.ports, p] });
            setPortInput("");
          }}>Add</button>
        </div>
        <div className="cp-chips" style={{ marginTop: 8 }}>
          {state.ports.map(p => (
            <span key={p} className="cp-chip">{p}
              <button type="button" onClick={() => update({ ports: state.ports.filter(x => x !== p) })}>×</button>
            </span>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 640, marginTop: 18 }}>
        <div className="cp-label">Volumes (HOST:CONTAINER)</div>
        <div style={{ display: "flex", gap: 6 }}>
          <input className="cp-input cp-input--mono" placeholder="/data:/var/data"
            value={volInput} onChange={e => setVolInput(e.target.value)} />
          <button type="button" className="cp-btn" onClick={() => {
            const v = volInput.trim();
            if (v && !state.volumes.includes(v)) update({ volumes: [...state.volumes, v] });
            setVolInput("");
          }}>Add</button>
        </div>
        <div className="cp-chips" style={{ marginTop: 8 }}>
          {state.volumes.map(v => (
            <span key={v} className="cp-chip">{v}
              <button type="button" onClick={() => update({ volumes: state.volumes.filter(x => x !== v) })}>×</button>
            </span>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 640, marginTop: 18 }}>
        <div className="cp-label">Env variables</div>
        <div className="vstack" style={{ gap: 6 }}>
          {state.env.map((e, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 6 }}>
              <input className="cp-input cp-input--mono" placeholder="KEY" value={e.key}
                onChange={ev => updateEnv(i, { key: ev.target.value })} />
              <input className="cp-input cp-input--mono" placeholder="value" value={e.value}
                onChange={ev => updateEnv(i, { value: ev.target.value })} />
              <button type="button" className="cp-btn cp-btn--sm"
                onClick={() => update({ env: state.env.filter((_, j) => j !== i) })}>×</button>
            </div>
          ))}
          <button type="button" className="cp-btn cp-btn--sm" style={{ alignSelf: "flex-start" }}
            onClick={() => update({ env: [...state.env, { key: "", value: "" }] })}>+ add env</button>
        </div>
      </div>

      <div style={{ maxWidth: 640, marginTop: 18 }}>
        <div className="cp-label">Healthcheck</div>
        <select className="cp-select" value={state.healthcheck.type}
          onChange={e => {
            const t = e.target.value;
            if (t === "none") update({ healthcheck: { type: "none" } });
            else update({ healthcheck: { type: "http", url: "", expectStatus: 200 } });
          }}>
          <option value="none">none</option>
          <option value="http">http</option>
        </select>
        {state.healthcheck.type === "http" && (
          <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "1fr 120px", gap: 6 }}>
            <input className="cp-input cp-input--mono" placeholder="http://127.0.0.1:80/healthz"
              value={state.healthcheck.url}
              onChange={e => update({ healthcheck: { type: "http", url: e.target.value, expectStatus: state.healthcheck.type === "http" ? state.healthcheck.expectStatus : 200 } })} />
            <input className="cp-input cp-input--mono" placeholder="200" type="number"
              value={state.healthcheck.expectStatus}
              onChange={e => update({ healthcheck: { type: "http", url: state.healthcheck.type === "http" ? state.healthcheck.url : "", expectStatus: parseInt(e.target.value) || 200 } })} />
          </div>
        )}
      </div>
    </section>
  );
}

function ReviewStep({ state }: { state: WizardState }) {
  const yaml = useMemo(() => generateYaml(state), [state]);
  const nav = useNavigate();
  const create = useCreateDeploy();
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onApply = async () => {
    setApplying(true); setError(null);
    try {
      const deploy = await create.mutateAsync(state.deployName);
      const r = await fetch(`/api/deploys/${deploy.id}/apply`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ yaml_text: yaml }),
      });
      if (!r.ok) {
        const body = await r.text();
        throw new Error(`apply failed: ${r.status} ${body.slice(0, 200)}`);
      }
      nav(`/deploys/${deploy.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  return (
    <section>
      <h1>Review</h1>
      <p className="dim">Generated YAML below. You can still go back and edit any step.</p>
      <pre className="cp-yaml" data-testid="wizard-yaml">{yaml}</pre>
      <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" className="cp-btn cp-btn--primary" onClick={onApply} disabled={applying || !state.deployName || state.hostIds.length === 0}>
          {applying ? "Applying…" : "Create deploy + apply"}
          <Icons.apply size={12} />
        </button>
        {error && <span className="small mono" style={{ color: "var(--err)" }}>{error}</span>}
        {state.deployName === "" && <span className="small dim"><Mono>deployName</Mono> missing — go back to Placement</span>}
      </div>
    </section>
  );
}
