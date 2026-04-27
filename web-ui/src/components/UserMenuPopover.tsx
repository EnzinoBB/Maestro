import { useEffect, useRef, useState } from "react";
import { Badge, Mono, Icons } from "../primitives";
import { useAuth } from "../hooks/useAuth";
import { ChangePasswordDialog } from "./ChangePasswordDialog";

const menuItemStyle: React.CSSProperties = {
  width: "100%", justifyContent: "flex-start", padding: "8px 10px",
  borderRadius: 4, gap: 10,
};

/**
 * Topbar avatar+username button that opens a popover with:
 *   - identity block (avatar + @username + role + email)
 *   - Change password (multi-user only)
 *   - Switch user (logout + redirect to /login, with confirm)
 *   - Sign out (logout, with confirm)
 *
 * In single-user mode the popover only shows the identity + an inline hint
 * about MAESTRO_SINGLE_USER_MODE.
 */
export function UserMenuPopover() {
  const { state, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState<null | "switch" | "out">(null);
  const [changing, setChanging] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (state.status !== "authenticated" && state.status !== "single-user") return null;

  const username = state.username;
  const isSingleUser = state.status === "single-user";
  const role: "admin" | "operator" = state.is_admin ? "admin" : "operator";
  const avatar = username.slice(0, 2).toUpperCase();
  const email = ""; // M5 schema has email but /api/auth/me doesn't expose it yet

  const onSignOutConfirmed = async () => {
    setConfirm(null);
    setOpen(false);
    await logout();
  };
  const onSwitchConfirmed = async () => {
    // Same as sign-out: server clears session, RequireAuth redirects to /login
    setConfirm(null);
    setOpen(false);
    await logout();
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        className="cp-btn cp-btn--ghost cp-btn--sm"
        onClick={() => setOpen(!open)}
        style={{ padding: "4px 6px", gap: 8 }}
      >
        <div style={{
          width: 22, height: 22, borderRadius: 999,
          background: "color-mix(in oklch, var(--accent) 22%, var(--bg-3))",
          display: "grid", placeItems: "center",
          fontSize: 10, fontWeight: 600,
        }}>{avatar}</div>
        <span style={{ fontSize: 11, fontWeight: 500 }}>@{username}</span>
        {isSingleUser && (
          <span style={{ fontSize: 10, color: "var(--fg-muted)", fontFamily: "var(--font-mono)" }}>
            (single-user)
          </span>
        )}
        <Icons.chevronDown size={11} />
      </button>

      {open && (
        <div className="cp-popover" style={{
          position: "absolute", right: 0, top: 36, width: 280, zIndex: 60,
        }}>
          <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
            <div className="hstack" style={{ gap: 10 }}>
              <div style={{
                width: 32, height: 32, borderRadius: 999,
                background: "color-mix(in oklch, var(--accent) 22%, var(--bg-3))",
                display: "grid", placeItems: "center", fontWeight: 600,
              }}>{avatar}</div>
              <div className="vstack" style={{ gap: 1, flex: 1 }}>
                <div className="hstack" style={{ gap: 6 }}>
                  <span style={{ fontWeight: 600 }}>@{username}</span>
                  <Badge status={role === "admin" ? "info" : "healthy"}>{role}</Badge>
                </div>
                <Mono dim style={{ fontSize: 11 }}>{email || "no email set"}</Mono>
              </div>
            </div>
          </div>

          {!isSingleUser ? (
            <div style={{ padding: 4 }}>
              <button type="button" className="cp-btn cp-btn--ghost" style={menuItemStyle}
                onClick={() => { setOpen(false); setChanging(true); }}>
                <Icons.settings size={13} /> <span>Change password</span>
              </button>
              <button type="button" className="cp-btn cp-btn--ghost" style={menuItemStyle}
                onClick={() => setConfirm("switch")}>
                <Icons.user size={13} /> <span>Switch user</span>
              </button>
              <div style={{ height: 1, background: "var(--border)", margin: "4px 6px" }} />
              <button type="button" className="cp-btn cp-btn--ghost cp-btn--danger" style={menuItemStyle}
                onClick={() => setConfirm("out")}>
                <Icons.x size={13} /> <span>Sign out</span>
              </button>
            </div>
          ) : (
            <div style={{ padding: 12 }}>
              <div className="small dim" style={{ lineHeight: 1.55 }}>
                Multi-user is off — set{" "}
                <Mono style={{
                  background: "var(--bg-2)", padding: "1px 5px",
                  borderRadius: 3, border: "1px solid var(--border)",
                }}>MAESTRO_SINGLE_USER_MODE=false</Mono>{" "}
                to enable login.
              </div>
            </div>
          )}
        </div>
      )}

      {confirm && (
        <ConfirmModal
          title={confirm === "switch" ? "Sign out and return to login?" : "Sign out?"}
          body={
            confirm === "switch"
              ? "Other users on this Control Plane can sign in here once you sign out."
              : "You'll need to sign in again to keep working."
          }
          primary={confirm === "switch" ? "Sign out & switch" : "Sign out"}
          onCancel={() => setConfirm(null)}
          onConfirm={confirm === "switch" ? onSwitchConfirmed : onSignOutConfirmed}
        />
      )}

      {changing && <ChangePasswordDialog onClose={() => setChanging(false)} />}
    </div>
  );
}

function ConfirmModal({
  title, body, primary, onCancel, onConfirm,
}: {
  title: string; body: string; primary: string;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <>
      <div className="cp-drawer-backdrop" onClick={onCancel} />
      <div className="cp-modal" style={{ zIndex: 70, width: 380 }}>
        <div style={{ padding: 18 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>{title}</div>
          <div className="small dim" style={{ lineHeight: 1.55 }}>{body}</div>
          <div className="hstack" style={{ justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
            <button type="button" className="cp-btn" onClick={onCancel}>Cancel</button>
            <button type="button" className="cp-btn cp-btn--primary" onClick={onConfirm}>{primary}</button>
          </div>
        </div>
      </div>
    </>
  );
}
