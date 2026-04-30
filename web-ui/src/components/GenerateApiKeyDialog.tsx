import { useEffect, useState } from "react";
import { Icons, Mono } from "../primitives";
import { copyText } from "../lib/clipboard";

type CreatedKey = {
  id: string;
  label: string;
  prefix: string;
  key: string;
};

async function createKey(label: string): Promise<CreatedKey> {
  const r = await fetch("/api/auth/keys", {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ label }),
  });
  const body = await r.json();
  if (!r.ok) {
    const code = body?.error?.code;
    const msg = body?.error?.message ?? `failed (${r.status})`;
    throw new ApiKeyCreateError(msg, code);
  }
  return body;
}

class ApiKeyCreateError extends Error {
  code: string | undefined;
  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

function configSnippet(cpUrl: string, key: string): string {
  return JSON.stringify({
    mcpServers: {
      maestro: {
        command: "python",
        args: ["-m", "app.mcp.server", "--control-plane", cpUrl],
        env: { MAESTRO_API_KEY: key },
      },
    },
  }, null, 2);
}

type CopyState = "idle" | "copied" | "failed";

export function GenerateApiKeyDialog({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<1 | 2>(1);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [copyKey, setCopyKey] = useState<CopyState>("idle");
  const [copyCfg, setCopyCfg] = useState<CopyState>("idle");

  const trimmed = label.trim();
  const labelValid =
    trimmed.length >= 1 && trimmed.length <= 64 && /^[a-z0-9-]+$/.test(trimmed);

  // ESC closes only on step 1 — step 2 forces explicit acknowledgement
  // because the cleartext key is shown only once.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && step === 1) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, onClose]);

  const submit = async () => {
    if (!labelValid) return;
    setBusy(true);
    setErr(null);
    try {
      const k = await createKey(trimmed);
      setCreated(k);
      setStep(2);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const onBackdrop = () => { if (step === 1) onClose(); };

  const cpUrl = window.location.origin;
  const snippet = created ? configSnippet(cpUrl, created.key) : "";

  const flashCopy = (
    setter: (s: CopyState) => void,
    text: string,
  ) => async () => {
    const ok = await copyText(text);
    setter(ok ? "copied" : "failed");
    setTimeout(() => setter("idle"), 1500);
  };

  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onBackdrop} />
      <div className={"cp-settings-modal" + (step === 2 ? " is-locked" : "")}>
        <div className="cp-settings-modal__head">
          <Icons.plus size={13} />
          <strong style={{ fontSize: 13 }}>Generate API key</strong>
          {step === 2 && (
            <Mono dim style={{ marginLeft: 8, fontSize: 11 }}>step 2 of 2</Mono>
          )}
          <div className="grow" />
          {step === 1 && (
            <button
              type="button"
              className="cp-btn cp-btn--ghost cp-btn--sm"
              onClick={onClose}
            >
              <Icons.x size={11} />
            </button>
          )}
        </div>

        {step === 1 && (
          <div className="cp-settings-modal__body">
            <span className="dim small" style={{ display: "block", marginBottom: 14 }}>
              Create a long-lived credential. The full key value is shown once on the
              next step — copy it before closing.
            </span>
            <div className="vstack" style={{ gap: 4 }}>
              <span className="cp-label">Label</span>
              <input
                className="cp-input cp-input--mono"
                value={label}
                onChange={e => { setLabel(e.target.value.toLowerCase()); setErr(null); }}
                placeholder="claude-desktop"
                autoFocus
                maxLength={64}
              />
              <span className="small mono dim">
                1–64 chars · lowercase, digits, hyphens · must be unique within your account
              </span>
            </div>
            {err && (
              <div className="cp-settings-errrow" style={{ marginTop: 12 }}>
                <Icons.alert size={12} />
                <span>{err}</span>
              </div>
            )}
            <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
              <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="cp-btn cp-btn--primary"
                disabled={!labelValid || busy}
                onClick={submit}
              >
                {busy ? "Generating…" : (
                  <>
                    <Icons.check size={11} />
                    <span>Generate</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {step === 2 && created && (
          <div className="cp-settings-modal__body">
            <div className="cp-settings-warnbanner">
              <Icons.alert size={13} />
              <div className="vstack" style={{ gap: 1, flex: 1 }}>
                <strong style={{ fontSize: 12 }}>Save it now.</strong>
                <span className="small" style={{ lineHeight: 1.5 }}>
                  Maestro stores only a hash. This is the only time you'll see the full
                  key — closing this dialog without copying means you'll need to revoke
                  and regenerate.
                </span>
              </div>
            </div>

            <div className="vstack" style={{ gap: 4, marginBottom: 14 }}>
              <span className="cp-label">API key</span>
              <div className="cp-settings-pwblock">
                <Mono style={{ fontSize: 12.5, flex: 1, userSelect: "all", wordBreak: "break-all" }}>
                  {created.key}
                </Mono>
                <button
                  type="button"
                  className="cp-btn cp-btn--sm"
                  onClick={flashCopy(setCopyKey, created.key)}
                >
                  <Icons.copy size={11} />
                  <span>{copyKey === "copied" ? "copied" : copyKey === "failed" ? "failed" : "copy"}</span>
                </button>
              </div>
            </div>

            <div className="cp-card cp-settings-cfgcard">
              <div className="cp-settings-cfgcard__head">
                <Icons.deploy size={12} className="dim" />
                <strong style={{ fontSize: 12 }}>MCP client config</strong>
                <span className="dim small">
                  — drop into <Mono>~/.config/claude-desktop/config.json</Mono>
                </span>
                <div className="grow" />
                <button
                  type="button"
                  className="cp-btn cp-btn--ghost cp-btn--sm"
                  onClick={flashCopy(setCopyCfg, snippet)}
                >
                  <Icons.copy size={11} />
                  <span>{copyCfg === "copied" ? "copied" : copyCfg === "failed" ? "failed" : "copy config"}</span>
                </button>
              </div>
              <pre className="cp-settings-cfgpre"><code>{snippet}</code></pre>
            </div>

            <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
              <button type="button" className="cp-btn cp-btn--primary" onClick={onClose}>
                <Icons.check size={11} />
                <span>I've saved it, close</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
