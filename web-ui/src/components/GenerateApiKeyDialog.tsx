export function GenerateApiKeyDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        <p>(Generate dialog — implemented in next task)</p>
        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
