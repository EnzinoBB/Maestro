import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export function LoginScreen() {
  const { state } = useAuth();
  const nav = useNavigate();

  // If already signed in (or running in single-user mode), nothing to do here.
  if (state.status === "authenticated" || state.status === "single-user") {
    nav("/", { replace: true });
    return null;
  }

  // First-run setup: no admin exists yet — show "Create admin" form
  // instead of asking for credentials that don't exist.
  if (state.status === "needs-setup") {
    return <SetupAdminForm onDone={() => nav("/", { replace: true })} />;
  }

  // Default: standard login form.
  return <SignInForm onDone={() => nav("/", { replace: true })} />;
}

function SignInForm({ onDone }: { onDone: () => void }) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null); setSubmitting(true);
    try {
      await login(username.trim(), password);
      onDone();
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
      </form>
    </div>
  );
}

function SetupAdminForm({ onDone }: { onDone: () => void }) {
  const { setupAdmin } = useAuth();
  const [username, setUsername] = useState("admin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const tooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit = username.length > 0 && password.length >= 8 && password === confirm;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null); setSubmitting(true);
    try {
      await setupAdmin(username.trim(), password, email.trim() || undefined);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="cp-login">
      <form className="cp-login__card" onSubmit={onSubmit} style={{ width: 420 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span className="cp-sidebar__brand-mark">M</span>
          <h1 style={{ margin: 0, fontSize: 18 }}>Maestro · first-run setup</h1>
        </div>
        <p className="small dim" style={{ marginTop: 0, marginBottom: 18, lineHeight: 1.5 }}>
          No admin exists yet on this Control Plane. Create the first admin
          account below — you'll be signed in automatically. After this,
          additional users are managed from the <strong>Admin</strong> page.
        </p>

        <div className="cp-label" style={{ marginBottom: 4 }}>Username</div>
        <input
          className="cp-input cp-input--mono"
          autoFocus
          value={username}
          onChange={e => setUsername(e.target.value)}
          autoComplete="username"
          required
        />

        <div className="cp-label" style={{ marginTop: 14, marginBottom: 4 }}>Email <span className="dim">(optional)</span></div>
        <input
          type="email"
          className="cp-input cp-input--mono"
          value={email}
          onChange={e => setEmail(e.target.value)}
          autoComplete="email"
          placeholder="you@example.com"
        />

        <div className="cp-label" style={{ marginTop: 14, marginBottom: 4 }}>Password <span className="dim">(min 8 chars)</span></div>
        <input
          type="password"
          className="cp-input cp-input--mono"
          value={password}
          onChange={e => setPassword(e.target.value)}
          autoComplete="new-password"
          required
        />
        {tooShort && (
          <div className="small" style={{ color: "var(--warn)", marginTop: 4 }}>
            password must be at least 8 characters
          </div>
        )}

        <div className="cp-label" style={{ marginTop: 14, marginBottom: 4 }}>Confirm password</div>
        <input
          type="password"
          className="cp-input cp-input--mono"
          value={confirm}
          onChange={e => setConfirm(e.target.value)}
          autoComplete="new-password"
          required
        />
        {mismatch && (
          <div className="small" style={{ color: "var(--warn)", marginTop: 4 }}>
            passwords don't match
          </div>
        )}

        <button
          type="submit"
          className="cp-btn cp-btn--primary"
          style={{ marginTop: 20, width: "100%", justifyContent: "center" }}
          disabled={submitting || !canSubmit}
        >
          {submitting ? "Creating admin…" : "Create admin & sign in"}
        </button>
        {error && (
          <div className="small mono" style={{ color: "var(--err)", marginTop: 10 }}>
            {error}
          </div>
        )}
      </form>
    </div>
  );
}
