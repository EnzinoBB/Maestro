import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Icons, Mono, Badge, StatusDot } from "../primitives";
import { Stepper } from "./Stepper";
import { copyText } from "../lib/clipboard";

type EnrollPayload = {
  cp_url: string;
  token: string;
  install_url: string;
  token_available: boolean;
  claim_user_id?: string;
};

type Node = {
  id: string;
  host_id: string;
  online: boolean;
  node_type: "user" | "shared";
  label: string | null;
  created_at: number;
};

async function fetchEnroll(): Promise<EnrollPayload> {
  const r = await fetch("/api/daemon-enroll", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`enroll fetch failed: ${r.status}`);
  return r.json();
}

async function fetchNodes(): Promise<{ nodes: Node[] }> {
  const r = await fetch("/api/nodes", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`nodes fetch failed: ${r.status}`);
  return r.json();
}

/**
 * 4-step right-side drawer that walks an admin through enrolling a daemon:
 *   0. Identity   — host_id (+ optional label, classification)
 *   1. Install    — generated curl|bash command with copy
 *   2. Waiting    — polls /api/nodes every 3s until the new host_id appears
 *   3. Confirm    — summary + close
 *
 * Replaces the ad-hoc inline panel from v0.2.6.
 */
export function EnrollDrawer({ onClose, onEnrolled, knownHostIds }: {
  onClose: () => void;
  onEnrolled?: (hostId: string) => void;
  knownHostIds: Set<string>;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [type, setType] = useState<"user" | "shared">("user");
  const [labels, setLabels] = useState("");

  const validName = /^[a-z0-9-]{2,}$/.test(name);

  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onClose} />
      <div className="cp-drawer" style={{ width: 560 }}>
        <div className="cp-drawer__header">
          <Icons.node size={14} />
          <div className="grow"><strong>Enroll a new node</strong></div>
          <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose}>
            <Icons.x size={14} />
          </button>
        </div>
        <Stepper
          steps={["Name", "Install command", "Waiting for daemon", "Confirm"]}
          current={step}
        />
        <div className="cp-drawer__body" style={{ padding: 0 }}>
          {step === 0 && (
            <Step0Identity
              name={name} setName={setName}
              type={type} setType={setType}
              labels={labels} setLabels={setLabels}
            />
          )}
          {step === 1 && <Step1Install hostId={name} type={type} labels={labels} />}
          {step === 2 && (
            <Step2Waiting
              hostId={name}
              knownHostIds={knownHostIds}
              onConnected={() => setStep(3)}
            />
          )}
          {step === 3 && <Step3Confirm hostId={name} type={type} labels={labels} />}
        </div>

        <div style={{
          padding: "12px 18px", borderTop: "1px solid var(--border)",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <button
            type="button" className="cp-btn"
            onClick={() => step === 0 ? onClose() : setStep(Math.max(0, step - 1))}
            disabled={step === 2 || step === 3}
          >
            {step === 0 ? "Cancel" : "← Back"}
          </button>
          <div className="hstack" style={{ gap: 8 }}>
            {step === 0 && (
              <button type="button" className="cp-btn cp-btn--primary"
                disabled={!validName} onClick={() => setStep(1)}>
                Generate command →
              </button>
            )}
            {step === 1 && (
              <button type="button" className="cp-btn cp-btn--primary"
                onClick={() => setStep(2)}>
                I've run it →
              </button>
            )}
            {step === 3 && (
              <button type="button" className="cp-btn cp-btn--primary"
                onClick={() => { onEnrolled?.(name); onClose(); }}>
                <Icons.check size={12} />
                <span>Done</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function Step0Identity({
  name, setName, type, setType, labels, setLabels,
}: {
  name: string; setName: (s: string) => void;
  type: "user" | "shared"; setType: (t: "user" | "shared") => void;
  labels: string; setLabels: (s: string) => void;
}) {
  const choices: { v: "user" | "shared"; t: string; d: string }[] = [
    { v: "user", t: "User node", d: "Owned by you. Only you can place components." },
    { v: "shared", t: "Shared node", d: "Visible to your org. Other admins can grant access." },
  ];
  return (
    <div style={{ padding: 18 }} className="vstack">
      <div className="vstack" style={{ gap: 4, marginBottom: 6 }}>
        <strong>Name and classify the node</strong>
        <span className="small dim">
          A node is any Linux/macOS host running the Maestro daemon. Pick a short,
          dns-1123-friendly name.
        </span>
      </div>
      <div>
        <div className="cp-label" style={{ marginBottom: 6 }}>Node name</div>
        <input className="cp-input cp-input--mono"
          value={name}
          onChange={e => setName(e.target.value.toLowerCase().replace(/\s+/g, ""))}
          placeholder="api-fra-03"
          autoFocus />
        <div className="small dim mono" style={{ marginTop: 4 }}>
          lowercase letters, digits, hyphens · 2+ chars
        </div>
      </div>
      <div>
        <div className="cp-label" style={{ marginBottom: 6 }}>Type</div>
        <div className="hstack" style={{ gap: 8 }}>
          {choices.map(o => (
            <label key={o.v} className="cp-card" style={{
              flex: 1, padding: 12, cursor: "pointer",
              borderColor: type === o.v ? "var(--accent)" : "var(--border)",
              boxShadow: type === o.v ? "inset 0 0 0 1px var(--accent)" : "none",
            }}>
              <div className="hstack" style={{ gap: 8, marginBottom: 4 }}>
                <input type="radio" checked={type === o.v} onChange={() => setType(o.v)} />
                <strong style={{ fontSize: 12 }}>{o.t}</strong>
              </div>
              <div className="small dim">{o.d}</div>
            </label>
          ))}
        </div>
      </div>
      <div>
        <div className="cp-label" style={{ marginBottom: 6 }}>
          Labels{" "}
          <span className="dim" style={{ textTransform: "none", letterSpacing: 0 }}>(comma-separated, optional)</span>
        </div>
        <input className="cp-input cp-input--mono"
          value={labels}
          onChange={e => setLabels(e.target.value)}
          placeholder="region=eu-fra,tier=app" />
        <div className="small dim" style={{ marginTop: 4 }}>
          Labels are stored locally on the node; M3.5 wizard placement filters can match them.
        </div>
      </div>
    </div>
  );
}

function Step1Install({ hostId, type: _type, labels: _labels }: { hostId: string; type: string; labels: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["daemon-enroll"],
    queryFn: fetchEnroll,
    refetchOnMount: "always",
  });
  const [copied, setCopied] = useState(false);
  const [copyErr, setCopyErr] = useState(false);

  if (isLoading) return <div style={{ padding: 18 }}><div className="cp-skel" style={{ height: 200 }} /></div>;
  if (error) {
    return (
      <div style={{ padding: 18 }}>
        <div className="cp-banner">
          <span className="cp-banner__dot" />
          <div className="small">Could not fetch enrollment details: <Mono>{String(error)}</Mono></div>
        </div>
      </div>
    );
  }
  if (!data) return null;

  const cmd = buildCommand(data, hostId);

  const onCopy = async () => {
    const ok = await copyText(cmd);
    if (ok) {
      setCopied(true);
      setCopyErr(false);
      setTimeout(() => setCopied(false), 1500);
    } else {
      setCopyErr(true);
      setTimeout(() => setCopyErr(false), 4000);
    }
  };

  return (
    <div style={{ padding: 18 }} className="vstack">
      <div className="vstack" style={{ gap: 4, marginBottom: 6 }}>
        <strong>Run this on the host</strong>
        <span className="small dim">
          SSH into <Mono>{hostId || "<host>"}</Mono> as root (or via sudo) and paste the command. The
          daemon will register itself with this Control Plane within a few seconds.
        </span>
      </div>

      {!data.token_available && (
        <div className="cp-banner">
          <span className="cp-banner__dot" />
          <div className="small">
            <strong>Daemon token not found.</strong>{" "}
            Set <Mono>MAESTRO_DAEMON_TOKEN</Mono> in the CP container environment, or check the
            container logs for "GENERATED MAESTRO DAEMON TOKEN".
          </div>
        </div>
      )}

      <div style={{
        position: "relative", background: "var(--bg)",
        border: "1px solid var(--border)", borderRadius: 4,
        padding: "10px 12px", paddingRight: 76,
      }}>
        <pre data-testid="enroll-command" style={{
          fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.6,
          margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", color: "var(--fg-dim)",
        }}>{cmd}</pre>
        <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm"
          style={{ position: "absolute", top: 6, right: 6 }}
          onClick={onCopy} disabled={!data.token_available}>
          <Icons.check size={12} />
          <span>{copied ? "copied" : copyErr ? "failed" : "copy"}</span>
        </button>
      </div>

      {copyErr && (
        <div className="small" style={{ color: "var(--err)", marginTop: -8 }}>
          Could not access the clipboard — select the command above and copy it manually.
        </div>
      )}

      <div className="hstack" style={{
        gap: 8, padding: 10,
        background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 4,
      }}>
        <Icons.alert size={14} />
        <div className="small dim" style={{ lineHeight: 1.5 }}>
          The daemon connects back over WebSocket; no inbound port is needed on the daemon host.
          Pass <Mono>--auto-update</Mono> to install a weekly upgrade timer; use{" "}
          <Mono>--insecure</Mono> if your CP URL is plain HTTP.
        </div>
      </div>
    </div>
  );
}

function Step2Waiting({ hostId, knownHostIds, onConnected }: {
  hostId: string;
  knownHostIds: Set<string>;
  onConnected: () => void;
}) {
  // Poll every 2s and check if the new hostId has shown up in /api/nodes.
  // The list of "already known before we opened the wizard" is captured by
  // the parent so we don't auto-advance just because *some* node was already
  // there.
  const { data } = useQuery({
    queryKey: ["nodes"],
    queryFn: fetchNodes,
    refetchInterval: 2000,
  });
  const matched = (data?.nodes || []).find(
    n => n.host_id === hostId && !knownHostIds.has(n.host_id),
  );
  useEffect(() => {
    if (matched) {
      const t = setTimeout(onConnected, 600);  // brief celebration
      return () => clearTimeout(t);
    }
  }, [matched, onConnected]);

  return (
    <div style={{ padding: 32, textAlign: "center" }}>
      <div style={{ display: "grid", placeItems: "center", marginBottom: 16 }}>
        <div className="cp-spinner" />
      </div>
      <strong style={{ fontSize: 14 }}>
        Waiting for {hostId || "the node"} to call home…
      </strong>
      <div className="small dim" style={{ marginTop: 8, lineHeight: 1.6 }}>
        The daemon usually checks in within 30 seconds of running the install command.
        This panel auto-advances when it appears.
      </div>
      <div className="hstack" style={{
        gap: 8, justifyContent: "center", marginTop: 18,
        padding: "8px 12px", background: "var(--bg-2)",
        borderRadius: 4, display: "inline-flex", border: "1px solid var(--border)",
      }}>
        <StatusDot status={matched ? "applying" : "unknown"} pulse={!!matched} />
        <Mono dim style={{ fontSize: 11 }}>
          {matched ? "host contacted — finalizing…" : "no contact yet"}
        </Mono>
      </div>
    </div>
  );
}

function Step3Confirm({ hostId, type, labels }: { hostId: string; type: string; labels: string }) {
  return (
    <div style={{ padding: 18 }} className="vstack">
      <div className="hstack" style={{
        gap: 10, padding: 14,
        background: "color-mix(in oklch, var(--ok) 8%, transparent)",
        border: "1px solid color-mix(in oklch, var(--ok) 30%, var(--border))",
        borderRadius: 4,
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 999,
          background: "var(--ok)", display: "grid", placeItems: "center",
          color: "var(--bg)", flexShrink: 0,
        }}>
          <Icons.check size={16} />
        </div>
        <div className="vstack" style={{ gap: 2 }}>
          <strong>Node enrolled.</strong>
          <span className="small dim"><Mono>{hostId}</Mono> is online and reporting metrics.</span>
        </div>
      </div>
      <div className="cp-card" style={{ padding: 14 }}>
        <div className="cp-section-title" style={{ marginBottom: 10 }}>Node summary</div>
        <div style={{
          display: "grid", gridTemplateColumns: "120px 1fr",
          rowGap: 8, fontSize: 12, alignItems: "start",
        }}>
          <span className="dim">Name</span><Mono>{hostId}</Mono>
          <span className="dim">Type</span>
          <span><Badge status={type === "shared" ? "info" : "healthy"}>{type}</Badge></span>
          {labels && <>
            <span className="dim">Labels</span>
            <Mono dim style={{ fontSize: 11 }}>{labels}</Mono>
          </>}
        </div>
      </div>
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
  if (p.claim_user_id) {
    lines[lines.length - 1] += " \\";
    lines.push(`      --claim ${p.claim_user_id}`);
  }
  return lines.join("\n");
}

/** Improved Nodes-empty state: a friendly card with three "what next" pills. */
export function NodesEmpty({ onEnroll, isAdmin }: { onEnroll: () => void; isAdmin: boolean }) {
  return (
    <div className="cp-card" style={{ padding: 40, textAlign: "center" }}>
      <div style={{
        width: 56, height: 56, borderRadius: 8,
        background: "var(--bg-2)", border: "1px solid var(--border)",
        display: "grid", placeItems: "center",
        margin: "0 auto 16px", color: "var(--fg-muted)",
      }}>
        <Icons.node size={26} />
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>No nodes yet.</div>
      <div className="dim" style={{ fontSize: 12, lineHeight: 1.6, maxWidth: 380, margin: "0 auto 20px" }}>
        Maestro deploys components onto Linux hosts running the <Mono>maestrod</Mono> daemon.
        Enroll your first host to start placing components.
      </div>
      {isAdmin && (
        <div className="hstack" style={{ gap: 8, justifyContent: "center" }}>
          <button type="button" className="cp-btn cp-btn--primary" onClick={onEnroll}>
            <Icons.plus size={12} />
            <span>Enroll a node</span>
          </button>
        </div>
      )}
      <div style={{
        marginTop: 24, paddingTop: 20, borderTop: "1px solid var(--border)",
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12,
        textAlign: "left", maxWidth: 540, margin: "24px auto 0",
      }}>
        {[
          { n: "1", t: "Pick a host", d: "Any Linux/macOS box you can SSH into. RPi to bare metal." },
          { n: "2", t: "Run one command", d: "We'll generate it. The daemon registers itself." },
          { n: "3", t: "Place components", d: "Use the Wizard to bind containers to this node." },
        ].map(x => (
          <div key={x.n} className="vstack" style={{ gap: 4 }}>
            <Mono dim style={{ fontSize: 11 }}>{`0${x.n}`}</Mono>
            <strong style={{ fontSize: 12 }}>{x.t}</strong>
            <span className="small dim">{x.d}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
