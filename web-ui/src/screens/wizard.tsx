import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { postDockerInspect, useCreateDeploy, useDeploys } from "../api/client";
import { Icons, Mono } from "../primitives";
import {
  initialWizardState, defaultComponentId,
  type WizardState, type SourceType, type EntryPoint,
} from "../wizard/types";
import { generateYaml, patchYaml } from "../wizard/yamlgen";

type StepId = "intent" | "source" | "source-details" | "placement" | "runtime" | "review";

function stepsForEntryPoint(ep: EntryPoint): { id: StepId; label: string }[] {
  if (ep === "upgrade-component") {
    return [
      { id: "intent", label: "Intent" },
      { id: "source", label: "Source" },
      { id: "source-details", label: "Source details" },
      { id: "review", label: "Review" },
    ];
  }
  return [
    { id: "intent", label: "Intent" },
    { id: "source", label: "Source" },
    { id: "source-details", label: "Source details" },
    { id: "placement", label: "Placement" },
    { id: "runtime", label: "Runtime" },
    { id: "review", label: "Review" },
  ];
}

export function WizardScreen() {
  const [params] = useSearchParams();
  const initialEntry = (params.get("entry") as EntryPoint) || "new";
  const initialDeployId = params.get("deploy") || undefined;
  const initialComponentId = params.get("component") || undefined;

  const [state, setState] = useState<WizardState>({
    ...initialWizardState,
    entryPoint: initialEntry,
    targetDeployId: initialDeployId,
    targetComponentId: initialComponentId,
  });
  const STEPS = stepsForEntryPoint(state.entryPoint);
  const [step, setStep] = useState<StepId>(STEPS[0].id);
  const stepIdx = STEPS.findIndex(s => s.id === step);
  const update = (patch: Partial<WizardState>) => setState(s => ({ ...s, ...patch }));

  useEffect(() => {
    const valid = STEPS.find(s => s.id === step);
    if (!valid) setStep(STEPS[0].id);
  }, [state.entryPoint]); // eslint-disable-line react-hooks/exhaustive-deps

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
            <div key={s.id}
              className={`cp-wiz__step${active ? " active" : ""}${done ? " done" : ""}`}
              onClick={() => { if (i <= stepIdx) setStep(s.id); }}>
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
        {step === "intent" && <IntentStep state={state} update={update} />}
        {step === "source" && <SourceStep state={state} update={update} />}
        {step === "source-details" && <SourceDetailsStep state={state} update={update} />}
        {step === "placement" && <PlacementStep state={state} update={update} />}
        {step === "runtime" && <RuntimeStep state={state} update={update} />}
        {step === "review" && <ReviewStep state={state} />}
        <div className="cp-wiz__footer">
          <button type="button" className="cp-btn" onClick={prev} disabled={stepIdx === 0}>
            Back
          </button>
          {step !== "review" && (
            <button type="button" className="cp-btn cp-btn--primary" onClick={next} disabled={!canGoNext}>
              Next
              <Icons.apply size={12} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function validateStep(s: WizardState, id: StepId): boolean {
  switch (id) {
    case "intent":
      if (s.entryPoint === "new") return true;
      return !!s.targetDeployId && (s.entryPoint === "add-component" || !!s.targetComponentId);
    case "source":
      return ["docker", "git", "archive"].includes(s.sourceType);
    case "source-details":
      if (s.entryPoint === "upgrade-component" && !s.componentId) return false;
      if (s.sourceType === "docker") return !!s.image && !!s.tag;
      if (s.sourceType === "git") return !!s.repo && !!s.ref;
      if (s.sourceType === "archive") return !!s.archivePath;
      return false;
    case "placement":
      if (s.entryPoint === "new") return s.deployName.length > 0 && s.hostIds.length > 0;
      return s.hostIds.length > 0;
    case "runtime":
      return s.healthcheck.type === "none" || !!s.healthcheck.url;
    case "review":
      return true;
  }
}

function summarizeStep(id: StepId, s: WizardState): string {
  switch (id) {
    case "intent":
      if (s.entryPoint === "new") return "create a new deploy";
      if (s.entryPoint === "add-component") return `add to ${s.targetDeployId || "(pick deploy)"}`;
      return `upgrade ${s.targetComponentId || "(pick component)"} in ${s.targetDeployId || "(pick deploy)"}`;
    case "source": return s.sourceType;
    case "source-details":
      if (s.sourceType === "docker") return s.image ? `${s.image}:${s.tag}` : "pick an image";
      if (s.sourceType === "git") return s.repo ? `${s.repo}@${s.ref}` : "pick a repo";
      return s.archivePath || "pick an archive";
    case "placement":
      return s.hostIds.length ? `${s.hostIds.length} host(s) · ${s.deployName || "(name?)"}` : "pick hosts";
    case "runtime":
      return `${s.env.length} env · ${s.ports.length} ports · ${s.volumes.length} volumes`;
    case "review":
      return "generated YAML";
  }
}

function IntentStep({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
  const deploys = useDeploys();
  const choices: { ep: EntryPoint; label: string; sub: string; icon: any }[] = [
    { ep: "new", label: "New deploy", sub: "Scaffold a fresh deploy from any source.", icon: Icons.plus },
    { ep: "add-component", label: "Add component", sub: "Append a new component to an existing deploy.", icon: Icons.deploy },
    { ep: "upgrade-component", label: "Upgrade component", sub: "Bump the source ref of an existing component.", icon: Icons.rotate },
  ];
  const targetDeploy = state.targetDeployId
    ? deploys.data?.deploys.find(d => d.id === state.targetDeployId)
    : null;
  return (
    <section>
      <h1>What do you want to do?</h1>
      <div className="cp-radio-cards" style={{ marginTop: 16 }}>
        {choices.map(c => (
          <div key={c.ep}
            className={`cp-radio-card${state.entryPoint === c.ep ? " selected" : ""}`}
            onClick={() => update({ entryPoint: c.ep, targetDeployId: undefined, targetComponentId: undefined })}>
            <div className="cp-radio-card__icon"><c.icon size={18} /></div>
            <div><strong>{c.label}</strong></div>
            <div className="small dim">{c.sub}</div>
          </div>
        ))}
      </div>
      {state.entryPoint !== "new" && (
        <div style={{ marginTop: 24, maxWidth: 640 }}>
          <div className="cp-label">Target deploy</div>
          <select className="cp-select" value={state.targetDeployId || ""}
            onChange={e => update({ targetDeployId: e.target.value || undefined, targetComponentId: undefined })}>
            <option value="">— pick a deploy —</option>
            {(deploys.data?.deploys || []).map(d => (
              <option key={d.id} value={d.id}>{d.name} ({d.id})</option>
            ))}
          </select>
          {state.entryPoint === "upgrade-component" && targetDeploy && (
            <div style={{ marginTop: 12 }}>
              <div className="cp-label">Component to upgrade</div>
              <input className="cp-input cp-input--mono"
                placeholder="component_id from current YAML"
                value={state.targetComponentId || ""}
                onChange={e => update({ targetComponentId: e.target.value, componentId: e.target.value })} />
              <div className="small dim" style={{ marginTop: 4 }}>
                Type the component_id as it appears in the deploy's current YAML.
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function SourceStep({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
  const choices: { st: SourceType; label: string; sub: string }[] = [
    { st: "docker", label: "Docker image", sub: "Inspect metadata, suggest ports / volumes / env." },
    { st: "git", label: "Git repository", sub: "Clone + build steps (defined in YAML)." },
    { st: "archive", label: "Archive (.tar)", sub: "Reference an artifact already on the daemon." },
  ];
  return (
    <section>
      <h1>Where does the code come from?</h1>
      <div className="cp-radio-cards" style={{ marginTop: 16 }}>
        {choices.map(c => (
          <div key={c.st}
            className={`cp-radio-card${state.sourceType === c.st ? " selected" : ""}`}
            onClick={() => update({ sourceType: c.st })}>
            <div className="cp-radio-card__icon"><Icons.deploy size={18} /></div>
            <div><strong>{c.label}</strong></div>
            <div className="small dim">{c.sub}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SourceDetailsStep({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
  return (
    <section>
      <h1>Source details</h1>
      {state.sourceType === "docker" && <DockerDetails state={state} update={update} />}
      {state.sourceType === "git" && <GitDetails state={state} update={update} />}
      {state.sourceType === "archive" && <ArchiveDetails state={state} update={update} />}

      <div style={{ marginTop: 20, maxWidth: 640 }}>
        <div className="cp-label">Component ID</div>
        <input className="cp-input cp-input--mono"
          value={state.componentId}
          placeholder={defaultComponentId(state)}
          onChange={e => update({ componentId: e.target.value })} />
        <div className="small dim" style={{ marginTop: 4 }}>
          {state.entryPoint === "upgrade-component"
            ? "Must match an existing component in the target deploy."
            : "Identifies this component inside the deploy."}
        </div>
      </div>
    </section>
  );
}

function DockerDetails({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
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
        componentId: state.componentId || defaultComponentId(state),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInspecting(false);
    }
  };
  return (
    <>
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
    </>
  );
}

function GitDetails({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 160px", gap: 12, maxWidth: 720 }}>
      <label>
        <div className="cp-label">Repository URL</div>
        <input className="cp-input cp-input--mono" placeholder="https://github.com/acme/web-api.git"
          value={state.repo} onChange={e => update({ repo: e.target.value })} />
      </label>
      <label>
        <div className="cp-label">Ref (branch / tag / sha)</div>
        <input className="cp-input cp-input--mono" placeholder="main"
          value={state.ref} onChange={e => update({ ref: e.target.value })} />
      </label>
    </div>
  );
}

function ArchiveDetails({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
  return (
    <div style={{ maxWidth: 720 }}>
      <div className="cp-label">Archive path (on the daemon's filesystem)</div>
      <input className="cp-input cp-input--mono" placeholder="/var/maestro/artifacts/web-2.8.1.tar.gz"
        value={state.archivePath} onChange={e => update({ archivePath: e.target.value })} />
      <div className="small dim" style={{ marginTop: 4 }}>
        Archive must already be present on the target daemon. Upload pipeline lands in M3.6.
      </div>
    </div>
  );
}

function PlacementStep({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
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
      {state.entryPoint === "new" && (
        <div style={{ maxWidth: 640 }}>
          <div className="cp-label">Deploy name</div>
          <input className="cp-input cp-input--mono" placeholder="webapp-prod"
            value={state.deployName} onChange={e => update({ deployName: e.target.value })} />
        </div>
      )}
      <div style={{ marginTop: 18, maxWidth: 640 }}>
        <div className="cp-label">Hosts {state.entryPoint === "add-component" && <span className="dim">(only first is bound; existing hosts kept)</span>}</div>
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
      {state.entryPoint === "new" && (
        <div style={{ marginTop: 18, maxWidth: 640 }}>
          <div className="cp-label">Strategy</div>
          <select className="cp-select" value={state.strategy}
            onChange={e => update({ strategy: e.target.value as WizardState["strategy"] })}>
            <option value="sequential">sequential</option>
            <option value="parallel">parallel</option>
            <option value="canary">canary</option>
          </select>
        </div>
      )}
    </section>
  );
}

function RuntimeStep({ state, update }: { state: WizardState; update: (p: Partial<WizardState>) => void }) {
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
              onChange={e => update({ healthcheck: { ...state.healthcheck as any, url: e.target.value } })} />
            <input className="cp-input cp-input--mono" placeholder="200" type="number"
              value={state.healthcheck.expectStatus}
              onChange={e => update({ healthcheck: { ...state.healthcheck as any, expectStatus: parseInt(e.target.value) || 200 } })} />
          </div>
        )}
      </div>
    </section>
  );
}

function ReviewStep({ state }: { state: WizardState }) {
  const nav = useNavigate();
  const create = useCreateDeploy();
  const [yaml, setYaml] = useState<string>("");
  const [loadingTarget, setLoadingTarget] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (state.entryPoint === "new") {
      setYaml(generateYaml(state));
      return;
    }
    if (!state.targetDeployId) return;
    setLoadingTarget(true);
    fetch(`/api/deploys/${state.targetDeployId}`, { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => {
        if (!alive) return;
        const cv = d.versions?.find((v: any) => v.version_n === d.current_version);
        if (!cv) {
          setYaml("# target deploy has no current version\n");
          return;
        }
        setYaml(patchYaml(cv.yaml_text, state));
      })
      .catch(e => alive && setYaml(`# error fetching target: ${String(e)}\n`))
      .finally(() => alive && setLoadingTarget(false));
    return () => { alive = false; };
  }, [state]);

  const onApply = async () => {
    setApplying(true); setError(null);
    try {
      let deployId = state.targetDeployId;
      if (state.entryPoint === "new") {
        const d = await create.mutateAsync(state.deployName);
        deployId = d.id;
      }
      const r = await fetch(`/api/deploys/${deployId}/apply`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ yaml_text: yaml }),
      });
      if (!r.ok) {
        const body = await r.text();
        throw new Error(`apply failed: ${r.status} ${body.slice(0, 200)}`);
      }
      nav(`/deploys/${deployId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const canApply = !applying && yaml.length > 0 && (
    state.entryPoint === "new"
      ? state.deployName.length > 0 && state.hostIds.length > 0
      : !!state.targetDeployId
  );

  return (
    <section>
      <h1>Review</h1>
      <p className="dim">
        {state.entryPoint === "new"
          ? "Generated YAML below."
          : state.entryPoint === "add-component"
            ? "Existing deploy YAML with the new component appended."
            : "Existing deploy YAML with the target component's source upgraded."}
      </p>
      {loadingTarget ? (
        <div className="cp-skel" style={{ height: 240 }} />
      ) : (
        <pre className="cp-yaml" data-testid="wizard-yaml">{yaml}</pre>
      )}
      <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
        <button type="button" className="cp-btn cp-btn--primary" onClick={onApply} disabled={!canApply}>
          {applying ? "Applying…" : state.entryPoint === "new" ? "Create deploy + apply" : "Apply patch"}
          <Icons.apply size={12} />
        </button>
        {error && <span className="small mono" style={{ color: "var(--err)" }}>{error}</span>}
        {state.entryPoint === "new" && state.deployName === "" &&
          <span className="small dim"><Mono>deployName</Mono> missing — go back to Placement</span>}
      </div>
    </section>
  );
}
