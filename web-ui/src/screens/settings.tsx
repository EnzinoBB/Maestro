import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { ChangePasswordDialog } from "../components/ChangePasswordDialog";
import { ApiKeysSection } from "../components/ApiKeysSection";

export function SettingsScreen() {
  const { state } = useAuth();
  const [changing, setChanging] = useState(false);

  if (state.status !== "authenticated") return null;

  return (
    <div className="cp-page">
      <h1>Settings</h1>

      <section style={{ marginTop: 24 }}>
        <h2>Account</h2>
        <dl>
          <dt>Username</dt><dd>{state.username}</dd>
          <dt>Role</dt><dd>{state.is_admin ? "admin" : "operator"}</dd>
        </dl>
        <button onClick={() => setChanging(true)}>Change password</button>
        {changing && (
          <ChangePasswordDialog onClose={() => setChanging(false)} />
        )}
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>API keys</h2>
        <ApiKeysSection />
      </section>
    </div>
  );
}
