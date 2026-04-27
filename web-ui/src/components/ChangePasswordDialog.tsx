import { useState } from "react";
import { Icons } from "../primitives";
import { PasswordStrength } from "./PasswordStrength";

/** POST /api/auth/change-password — narrow modal anchored to the topbar UserMenu. */
export function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [cf, setCf] = useState("");
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const valid = !!cur && nw.length >= 8 && nw === cf;

  const submit = async () => {
    if (!valid) return;
    setSubmitting(true);
    setErr(null);
    try {
      const r = await fetch("/api/auth/change-password", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ old_password: cur, new_password: nw }),
      });
      if (!r.ok) {
        const body = await r.text();
        if (r.status === 403) throw new Error("Current password is wrong");
        throw new Error(body || `change failed (${r.status})`);
      }
      setDone(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onClose} />
      <div className="cp-modal" style={{ zIndex: 70, width: 420 }}>
        <div className="cp-drawer__header">
          <Icons.settings size={14} />
          <div className="grow"><strong>Change password</strong></div>
          <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose}>
            <Icons.x size={14} />
          </button>
        </div>
        <div style={{ padding: 18 }}>
          {done ? (
            <div>
              <div className="hstack" style={{
                gap: 8, color: "var(--ok)", padding: 12,
                background: "color-mix(in oklch, var(--ok) 8%, transparent)",
                border: "1px solid color-mix(in oklch, var(--ok) 30%, var(--border))",
                borderRadius: 4,
              }}>
                <Icons.check size={14} />
                <div className="vstack" style={{ gap: 2 }}>
                  <div style={{ fontWeight: 500 }}>Password changed.</div>
                  <div className="small dim" style={{ color: "var(--fg-dim)" }}>
                    You stay signed in on this device.
                  </div>
                </div>
              </div>
              <div className="hstack" style={{ justifyContent: "flex-end", marginTop: 16 }}>
                <button type="button" className="cp-btn cp-btn--primary" onClick={onClose}>Done</button>
              </div>
            </div>
          ) : (
            <div className="vstack" style={{ gap: 12 }}>
              <div>
                <div className="hstack" style={{ justifyContent: "space-between", marginBottom: 6 }}>
                  <span className="cp-label">Current password</span>
                  <button type="button" className="cp-btn cp-btn--ghost cp-btn--sm" onClick={() => setShow(!show)}>
                    {show ? "hide" : "show"}
                  </button>
                </div>
                <input className="cp-input cp-input--mono" type={show ? "text" : "password"}
                  value={cur} onChange={e => { setCur(e.target.value); setErr(null); }} autoFocus />
              </div>
              <div>
                <div className="cp-label" style={{ marginBottom: 6 }}>New password</div>
                <input className="cp-input cp-input--mono" type={show ? "text" : "password"}
                  value={nw} onChange={e => { setNw(e.target.value); setErr(null); }} />
                <PasswordStrength value={nw} />
              </div>
              <div>
                <div className="cp-label" style={{ marginBottom: 6 }}>Confirm new password</div>
                <input className="cp-input cp-input--mono" type={show ? "text" : "password"}
                  value={cf} onChange={e => { setCf(e.target.value); setErr(null); }} />
                {cf && nw !== cf && (
                  <div className="small" style={{ color: "var(--err)", marginTop: 4 }}>Passwords don't match</div>
                )}
              </div>
              {err && (
                <div style={{
                  color: "var(--err)", fontSize: 11, padding: "6px 10px",
                  background: "color-mix(in oklch, var(--err) 8%, transparent)", borderRadius: 4,
                }}>{err}</div>
              )}
              <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 6 }}>
                <button type="button" className="cp-btn" onClick={onClose}>Cancel</button>
                <button type="button" className="cp-btn cp-btn--primary"
                  disabled={!valid || submitting} onClick={submit}>
                  {submitting ? "Changing…" : <><Icons.check size={12} /><span>Change password</span></>}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
