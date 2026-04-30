import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Icons } from "../primitives";
import { useAuth } from "../hooks/useAuth";

const menuItemStyle: React.CSSProperties = {
  width: "100%", justifyContent: "flex-start", padding: "8px 10px",
  borderRadius: 4, gap: 10,
};

/**
 * Topbar avatar+username button that opens a popover with:
 *   - identity block (avatar + @username + role)
 *   - Settings (navigate to /settings)
 *   - Switch user (logout + redirect to /login, with confirm)
 *   - Sign out (logout, with confirm)
 */
export function UserMenuPopover() {
  const { state, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState<null | "switch" | "out">(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (state.status !== "authenticated") return null;

  const username = state.username;
  const role: "admin" | "operator" = state.is_admin ? "admin" : "operator";
  const avatar = username.slice(0, 2).toUpperCase();

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
              </div>
            </div>
          </div>

          <div style={{ padding: 4 }}>
            <Link to="/settings" onClick={() => setOpen(false)}>
              <button type="button" className="cp-btn cp-btn--ghost" style={menuItemStyle}>
                <Icons.settings size={13} /> <span>Settings</span>
              </button>
            </Link>
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
