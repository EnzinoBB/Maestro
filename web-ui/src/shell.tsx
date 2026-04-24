import { type ReactNode, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Icons, StatusDot } from "./primitives";
import { useHosts } from "./api/client";

type NavItem = { to: string; label: string; icon: (p: { size?: number }) => ReactNode };

const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: Icons.dashboard },
  { to: "/deploys", label: "Deploys", icon: Icons.deploy },
  { to: "/nodes", label: "Nodes", icon: Icons.node },
  { to: "/wizard", label: "Wizard", icon: Icons.wizard },
];

function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const t = localStorage.getItem("cp-theme");
    return t === "light" ? "light" : "dark";
  });
  const apply = (t: "dark" | "light") => {
    setTheme(t);
    localStorage.setItem("cp-theme", t);
    document.documentElement.dataset.theme = t;
  };
  // initial paint
  if (document.documentElement.dataset.theme !== theme) {
    document.documentElement.dataset.theme = theme;
  }
  return { theme, setTheme: apply };
}

export function Shell({ children }: { children: ReactNode }) {
  const { theme, setTheme } = useTheme();
  const loc = useLocation();
  const hosts = useHosts();
  const onlineCount = hosts.data?.hosts.filter(h => h.online).length ?? 0;
  const totalHosts = hosts.data?.hosts.length ?? 0;

  // Breadcrumb — crude but functional: splits pathname
  const crumbs = loc.pathname === "/"
    ? [{ label: "Overview", to: "/" }]
    : [
        { label: "Overview", to: "/" },
        ...loc.pathname.split("/").filter(Boolean).map((seg, i, arr) => ({
          label: seg,
          to: "/" + arr.slice(0, i + 1).join("/"),
        })),
      ];

  return (
    <div className="cp-app">
      <aside className="cp-sidebar">
        <div className="cp-sidebar__brand">
          <span className="cp-sidebar__brand-mark">M</span>
          <span>Maestro</span>
        </div>
        <nav className="cp-sidebar__nav">
          {NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `cp-nav-item${isActive ? " active" : ""}`}
            >
              <item.icon size={16} />
              <span className="cp-nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="cp-sidebar__footer">
          <StatusDot status={onlineCount > 0 ? "online" : "offline"} size={6} />
          <span>{onlineCount}/{totalHosts} daemons</span>
        </div>
      </aside>

      <header className="cp-topbar">
        <nav className="cp-breadcrumb" aria-label="breadcrumb">
          {crumbs.map((c, i) => (
            <span key={c.to} style={{ display: "contents" }}>
              {i > 0 && <span>/</span>}
              <NavLink
                to={c.to}
                end={c.to === "/"}
                className={({ isActive }) => (isActive ? "crumb-active" : "")}
              >
                <button type="button">{c.label}</button>
              </NavLink>
            </span>
          ))}
        </nav>
        <div className="cp-topbar__spacer" />
        <div className="cp-topbar__right">
          <div className="cp-ws-indicator">
            <StatusDot status={onlineCount > 0 ? "online" : "offline"} size={6} pulse={onlineCount > 0} />
            <span>live</span>
          </div>
          <button
            type="button"
            className="cp-btn cp-btn--ghost cp-btn--sm"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Icons.sun size={14} /> : <Icons.moon size={14} />}
          </button>
        </div>
      </header>

      <main className="cp-main">{children}</main>
    </div>
  );
}
