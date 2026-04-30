import { useState } from "react";
import { Mono, Badge, Icons } from "../primitives";
import { useAuth } from "../hooks/useAuth";
import { ChangePasswordDialog } from "../components/ChangePasswordDialog";
import { ApiKeysSection } from "../components/ApiKeysSection";

export function SettingsScreen() {
  const { state } = useAuth();
  const [changing, setChanging] = useState(false);

  if (state.status !== "authenticated") return null;

  const role: "admin" | "operator" = state.is_admin ? "admin" : "operator";

  return (
    <div className="cp-page" style={{ maxWidth: 1080, padding: "20px 24px 40px" }}>
      <div className="cp-settings-header">
        <div className="vstack" style={{ gap: 4, minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Settings
          </h1>
          <span className="dim" style={{ fontSize: 12 }}>
            Your account and credentials for the Maestro Control Plane.
          </span>
        </div>
        <div className="cp-settings-headermeta">
          <Mono style={{ fontSize: 12 }}>@{state.username}</Mono>
          <span style={{ width: 1, height: 12, background: "var(--border)" }} />
          <Badge status={role === "admin" ? "info" : "healthy"}>{role}</Badge>
        </div>
      </div>

      <AccountSection
        username={state.username}
        role={role}
        onChangePw={() => setChanging(true)}
      />
      <ApiKeysSection />

      {changing && <ChangePasswordDialog onClose={() => setChanging(false)} />}
    </div>
  );
}

function AccountSection({
  username, role, onChangePw,
}: {
  username: string;
  role: "admin" | "operator";
  onChangePw: () => void;
}) {
  return (
    <section className="cp-settings-section">
      <div className="cp-settings-sectionhead">
        <div className="vstack" style={{ gap: 2 }}>
          <span className="cp-section-title">Account</span>
          <span className="dim small">Identity used for audit logs and key ownership.</span>
        </div>
      </div>
      <div className="cp-card cp-settings-account">
        <div className="cp-settings-kv">
          <div className="cp-settings-kv__row">
            <span className="cp-settings-kv__k">Username</span>
            <Mono style={{ fontSize: 13 }}>@{username}</Mono>
          </div>
          <div className="cp-settings-kv__row">
            <span className="cp-settings-kv__k">Role</span>
            <Badge status={role === "admin" ? "info" : "healthy"}>{role}</Badge>
          </div>
        </div>
        <div className="cp-settings-account__foot">
          <button type="button" className="cp-btn cp-btn--primary cp-btn--sm" onClick={onChangePw}>
            <Icons.rotate size={11} />
            <span>Change password</span>
          </button>
        </div>
      </div>
    </section>
  );
}
