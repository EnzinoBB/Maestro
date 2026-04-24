import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { Mono } from "../primitives";

export function LoginScreen() {
  const { state, login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // If we're already authenticated (or running in single-user mode), send
  // them home — there's nothing to do on /login.
  if (state.status === "authenticated" || state.status === "single-user") {
    nav("/", { replace: true });
    return null;
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null); setSubmitting(true);
    try {
      await login(username.trim(), password);
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="cp-login">
      <form className="cp-login__card" onSubmit={onSubmit}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
          <span className="cp-sidebar__brand-mark">M</span>
          <h1 style={{ margin: 0, fontSize: 18 }}>Maestro</h1>
        </div>
        <div className="cp-label" style={{ marginBottom: 4 }}>Username</div>
        <input
          className="cp-input cp-input--mono"
          autoFocus
          value={username}
          onChange={e => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
        <div className="cp-label" style={{ marginTop: 14, marginBottom: 4 }}>Password</div>
        <input
          type="password"
          className="cp-input cp-input--mono"
          value={password}
          onChange={e => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
        <button
          type="submit"
          className="cp-btn cp-btn--primary"
          style={{ marginTop: 20, width: "100%", justifyContent: "center" }}
          disabled={submitting || !username || !password}
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        {error && (
          <div className="small mono" style={{ color: "var(--err)", marginTop: 10 }}>
            {error}
          </div>
        )}
        <div className="small dim" style={{ marginTop: 18, lineHeight: 1.5 }}>
          Single-user mode? Set up multi-user by POSTing to{" "}
          <Mono>/api/auth/setup-admin</Mono> (or re-run the installer with
          <Mono> MAESTRO_SINGLE_USER_MODE=false</Mono>).
        </div>
      </form>
    </div>
  );
}
