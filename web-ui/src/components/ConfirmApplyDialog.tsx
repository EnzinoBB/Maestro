import type { DeployDiff } from "../api/client";

export function ConfirmApplyDialog({
  diff,
  onConfirm,
  onCancel,
  busy,
}: {
  diff: DeployDiff["diff"];
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const created = diff.created || [];
  const updated = diff.updated || [];
  const removed = diff.removed || [];

  return (
    <div className="cp-modal-backdrop" role="dialog" aria-modal="true">
      <div className="cp-modal">
        <h3 style={{ margin: "0 0 12px 0" }}>Apply changes?</h3>
        <ul className="cp-modal__list">
          <li><strong>{created.length}</strong> created</li>
          <li><strong>{updated.length}</strong> updated</li>
          <li><strong>{removed.length}</strong> removed</li>
        </ul>
        {removed.length > 0 && (
          <div className="cp-modal__warn">
            ⚠ Components removed in YAML are <strong>not removed</strong> from hosts in Phase 2.
            Use the wizard's remove flow (Phase 3) for full prune.
          </div>
        )}
        <div className="cp-modal__actions">
          <button type="button" className="cp-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="cp-btn cp-btn--primary" onClick={onConfirm} disabled={busy}>
            {busy ? "Applying…" : "Apply"}
          </button>
        </div>
      </div>
    </div>
  );
}
