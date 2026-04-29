export function RevokeApiKeyDialog({
  label, onConfirm, onClose,
}: { label: string; onConfirm: () => Promise<void>; onClose: () => void }) {
  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        <p>(Revoke '{label}' — implemented in next task)</p>
        <button onClick={() => onConfirm()}>Confirm</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}
