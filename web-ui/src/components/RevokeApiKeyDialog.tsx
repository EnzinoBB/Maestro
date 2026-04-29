import { useState } from "react";

export function RevokeApiKeyDialog({
  label, onConfirm, onClose,
}: { label: string; onConfirm: () => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const click = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        <h3>Revoke key</h3>
        <p>
          Revoke key <strong>'{label}'</strong>? Tools using this key will
          stop working immediately. This cannot be undone.
        </p>
        {err && <p style={{ color: "crimson" }}>{err}</p>}
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button onClick={onClose} disabled={busy}>Cancel</button>
          <button
            onClick={click}
            disabled={busy}
            style={{ background: "crimson", color: "white" }}
          >
            {busy ? "Revoking…" : "Revoke"}
          </button>
        </div>
      </div>
    </div>
  );
}
