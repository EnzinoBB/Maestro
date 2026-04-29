import { useState } from "react";

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
    const msg = body?.error?.message ?? `failed (${r.status})`;
    throw new Error(msg);
  }
  return body;
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

export function GenerateApiKeyDialog({ onClose }: { onClose: () => void }) {
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      const k = await createKey(label.trim());
      setCreated(k);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const cpUrl = window.location.origin;
  const snippet = created ? configSnippet(cpUrl, created.key) : "";

  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        {!created ? (
          <>
            <h3>Generate API key</h3>
            <label>
              Label
              <input
                autoFocus
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={64}
                placeholder="e.g. claude-code-laptop"
              />
            </label>
            {err && <p style={{ color: "crimson" }}>{err}</p>}
            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              <button onClick={onClose}>Cancel</button>
              <button
                disabled={!label.trim() || busy}
                onClick={submit}
              >
                {busy ? "Generating…" : "Generate"}
              </button>
            </div>
          </>
        ) : (
          <>
            <h3>Save your API key</h3>
            <p style={{ background: "#fff7d6", padding: 8, borderRadius: 4 }}>
              <strong>Save this key now. You won't be able to see it again.</strong>
            </p>
            <input readOnly value={created.key} style={{ width: "100%" }} />
            <button onClick={() => navigator.clipboard.writeText(created.key)}>
              Copy key
            </button>

            <h4 style={{ marginTop: 16 }}>MCP client config</h4>
            <pre style={{ background: "#f5f5f5", padding: 8, overflowX: "auto" }}>
              {snippet}
            </pre>
            <button onClick={() => navigator.clipboard.writeText(snippet)}>
              Copy config
            </button>

            <div style={{ marginTop: 16 }}>
              <button onClick={onClose}>I've saved it, close</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
