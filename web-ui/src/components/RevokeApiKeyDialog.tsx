import { useEffect, useState } from "react";
import { Icons, Mono } from "../primitives";

export function RevokeApiKeyDialog({
  label, onConfirm, onClose,
}: {
  label: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const click = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onClose} />
      <div className="cp-settings-modal cp-settings-modal--narrow">
        <div className="cp-settings-modal__head">
          <span style={{ color: "var(--err)", display: "inline-flex" }}>
            <Icons.alert size={13} />
          </span>
          <strong style={{ fontSize: 13 }}>Revoke API key</strong>
          <div className="grow" />
          <button
            type="button"
            className="cp-btn cp-btn--ghost cp-btn--sm"
            onClick={onClose}
          >
            <Icons.x size={11} />
          </button>
        </div>
        <div className="cp-settings-modal__body">
          <p style={{ fontSize: 13, lineHeight: 1.55, margin: "0 0 12px" }}>
            Revoke key{" "}
            <Mono style={{
              background: "var(--bg-2)", padding: "1px 5px", borderRadius: 3,
            }}>{label}</Mono>?
          </p>
          <p className="small dim" style={{ margin: 0, lineHeight: 1.55 }}>
            Tools using this key will start receiving{" "}
            <Mono>401 Unauthorized</Mono> on their next request. This cannot be undone —
            you'll need to generate a new key.
          </p>
          {err && (
            <div className="cp-settings-errrow" style={{ marginTop: 12 }}>
              <Icons.alert size={12} />
              <span>{err}</span>
            </div>
          )}
          <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
            <button type="button" className="cp-btn cp-btn--ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className="cp-btn cp-btn--danger"
              disabled={busy}
              onClick={click}
            >
              {busy ? "Revoking…" : (
                <>
                  <Icons.trash size={11} />
                  <span>Revoke key</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
