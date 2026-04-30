import { useEffect, useRef, useState, type ReactNode, type CSSProperties } from "react";

export type StatusKey =
  | "healthy" | "degraded" | "failed" | "applying" | "unknown"
  | "online" | "offline" | "success" | "in-progress" | "info"
  | "warning" | "warn" | "critical";

export const STATUS: Record<StatusKey, { label: string; color: string }> = {
  healthy:      { label: "Healthy",     color: "var(--ok)"    },
  degraded:     { label: "Degraded",    color: "var(--warn)"  },
  failed:       { label: "Failed",      color: "var(--err)"   },
  applying:     { label: "Applying",    color: "var(--info)"  },
  unknown:      { label: "Unknown",     color: "var(--muted)" },
  online:       { label: "Online",      color: "var(--ok)"    },
  offline:      { label: "Offline",     color: "var(--err)"   },
  success:      { label: "Success",     color: "var(--ok)"    },
  "in-progress":{ label: "In progress", color: "var(--info)"  },
  info:         { label: "Info",        color: "var(--info)"  },
  warning:      { label: "Warning",     color: "var(--warn)"  },
  warn:         { label: "Warning",     color: "var(--warn)"  },
  critical:     { label: "Critical",    color: "var(--err)"   },
};

function resolveStatus(s: string | undefined): { label: string; color: string } {
  if (!s) return STATUS.unknown;
  return STATUS[s as StatusKey] || STATUS.unknown;
}

export function StatusDot({
  status, size = 8, pulse, title,
}: { status: string; size?: number; pulse?: boolean; title?: string }) {
  const s = resolveStatus(status);
  const animated = pulse || status === "applying" || status === "in-progress";
  return (
    <span
      title={title || s.label}
      className={animated ? "cp-dot cp-dot--pulse" : "cp-dot"}
      style={{
        width: size,
        height: size,
        background: s.color,
        boxShadow: `0 0 0 3px color-mix(in oklch, ${s.color} 20%, transparent)`,
      }}
    />
  );
}

export function Badge({
  status, children, icon, mono,
}: { status?: string; children: ReactNode; icon?: ReactNode; mono?: boolean }) {
  const s = status ? resolveStatus(status) : null;
  const color = s ? s.color : "var(--fg-muted)";
  return (
    <span
      className="cp-badge"
      style={{
        borderColor: `color-mix(in oklch, ${color} 40%, var(--border))`,
        color: `color-mix(in oklch, ${color} 80%, var(--fg))`,
      }}
    >
      {icon}
      <span style={{ fontFamily: mono ? "var(--font-mono)" : "inherit" }}>{children}</span>
    </span>
  );
}

export function Pill({ status, children }: { status: string; children?: ReactNode }) {
  const s = resolveStatus(status);
  return (
    <span
      className="cp-pill"
      style={{
        color: s.color,
        borderColor: `color-mix(in oklch, ${s.color} 35%, transparent)`,
        background: `color-mix(in oklch, ${s.color} 10%, transparent)`,
      }}
    >
      <StatusDot status={status} size={6} />
      {children || s.label}
    </span>
  );
}

export function Sparkline({
  data, width = 100, height = 30, color = "var(--accent)", fill = true, strokeWidth = 1.2,
}: {
  data: { t: number; v: number }[];
  width?: number; height?: number; color?: string; fill?: boolean; strokeWidth?: number;
}) {
  if (!data || !data.length) return null;
  const min = Math.min(...data.map(d => d.v));
  const max = Math.max(...data.map(d => d.v));
  const range = max - min || 1;
  const step = width / (data.length - 1 || 1);
  const pts = data.map((d, i) => [i * step, height - ((d.v - min) / range) * (height - 2) - 1]);
  const path = pts.map((p, i) => (i === 0 ? `M${p[0].toFixed(1)},${p[1].toFixed(1)}` : `L${p[0].toFixed(1)},${p[1].toFixed(1)}`)).join(" ");
  const area = `${path} L${width},${height} L0,${height} Z`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {fill && <path d={area} fill={color} opacity={0.12} />}
      <path d={path} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function AreaChart({
  data, height = 180, color = "var(--accent)", yLabel, format = (v: number) => `${v.toFixed(0)}%`,
}: {
  data: { t: number; v: number }[];
  height?: number; color?: string; yLabel?: string; format?: (v: number) => string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [hover, setHover] = useState<{ idx: number; x: number; y: number; v: number } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const padL = 36, padR = 8, padT = 10, padB = 22;
  const iw = Math.max(10, w - padL - padR);
  const ih = height - padT - padB;
  const min = 0, max = 100;
  const step = iw / (data.length - 1 || 1);
  const pts = data.map((d, i) => [padL + i * step, padT + ih - ((d.v - min) / (max - min)) * ih] as const);
  const path = pts.map((p, i) => (i === 0 ? `M${p[0].toFixed(1)},${p[1].toFixed(1)}` : `L${p[0].toFixed(1)},${p[1].toFixed(1)}`)).join(" ");
  const area = `${path} L${padL + iw},${padT + ih} L${padL},${padT + ih} Z`;
  const yticks = [0, 25, 50, 75, 100];
  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const idx = Math.round((x - padL) / step);
    if (idx < 0 || idx >= data.length) { setHover(null); return; }
    setHover({ idx, x: pts[idx][0], y: pts[idx][1], v: data[idx].v });
  }
  return (
    <div ref={ref} style={{ width: "100%", position: "relative" }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg width={w} height={height} style={{ display: "block" }}>
        {yticks.map(yt => {
          const y = padT + ih - (yt / 100) * ih;
          return (
            <g key={yt}>
              <line x1={padL} x2={padL + iw} y1={y} y2={y} stroke="var(--border)" strokeDasharray="2,4" />
              <text x={padL - 6} y={y + 3} fill="var(--fg-muted)" fontSize="10" textAnchor="end" fontFamily="var(--font-mono)">{yt}</text>
            </g>
          );
        })}
        <path d={area} fill={color} opacity={0.14} />
        <path d={path} fill="none" stroke={color} strokeWidth={1.4} strokeLinejoin="round" />
        {hover && (
          <g>
            <line x1={hover.x} x2={hover.x} y1={padT} y2={padT + ih} stroke="var(--fg-muted)" strokeDasharray="2,3" />
            <circle cx={hover.x} cy={hover.y} r="3" fill={color} stroke="var(--bg)" strokeWidth="1.5" />
          </g>
        )}
        {yLabel && <text x={padL} y={padT - 2} fill="var(--fg-muted)" fontSize="10" fontFamily="var(--font-mono)">{yLabel}</text>}
      </svg>
      {hover && (
        <div className="cp-tooltip" style={{ left: hover.x, top: hover.y - 10 }}>
          <span style={{ color: "var(--fg)" }}>{format(hover.v)}</span>
          <span style={{ color: "var(--fg-muted)", marginLeft: 6, fontFamily: "var(--font-mono)" }}>t-{data.length - hover.idx}m</span>
        </div>
      )}
    </div>
  );
}

// ---- Icons (ported from prototype, kept inline SVG for zero-dep) ---------
type IconProps = { size?: number; className?: string };
function I({ d, size = 14, className }: IconProps & { d: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"
      strokeLinejoin="round" className={className}>
      {d}
    </svg>
  );
}
export const Icons = {
  dashboard: (p: IconProps) => <I {...p} d={<><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></>} />,
  deploy:    (p: IconProps) => <I {...p} d={<><path d="M12 2 3 7l9 5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/></>} />,
  node:      (p: IconProps) => <I {...p} d={<><rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><circle cx="7" cy="7" r=".5" fill="currentColor"/><circle cx="7" cy="17" r=".5" fill="currentColor"/></>} />,
  wizard:    (p: IconProps) => <I {...p} d={<><path d="M5 3v4M3 5h4"/><path d="M6 17v4M4 19h4"/><path d="M14 3l3 3-8 8-3-3 8-8z"/><path d="M12 13l4 4"/></>} />,
  admin:     (p: IconProps) => <I {...p} d={<><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/></>} />,
  sun:       (p: IconProps) => <I {...p} d={<><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></>} />,
  moon:      (p: IconProps) => <I {...p} d={<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>} />,
  plus:      (p: IconProps) => <I {...p} d={<><path d="M12 5v14M5 12h14"/></>} />,
  more:      (p: IconProps) => <I {...p} d={<><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></>} />,
  check:     (p: IconProps) => <I {...p} d={<path d="M20 6 9 17l-5-5"/>} />,
  x:         (p: IconProps) => <I {...p} d={<><path d="M18 6 6 18M6 6l12 12"/></>} />,
  alert:     (p: IconProps) => <I {...p} d={<><path d="M12 2 2 20h20z"/><path d="M12 9v5M12 18v.01"/></>} />,
  bell:      (p: IconProps) => <I {...p} d={<><path d="M6 8a6 6 0 1 1 12 0c0 7 3 7 3 10H3c0-3 3-3 3-10z"/><path d="M10 21h4"/></>} />,
  rotate:    (p: IconProps) => <I {...p} d={<><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></>} />,
  apply:     (p: IconProps) => <I {...p} d={<><path d="M5 12l5 5 10-10"/><path d="M5 19h14"/></>} />,
  clock:     (p: IconProps) => <I {...p} d={<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>} />,
  user:      (p: IconProps) => <I {...p} d={<><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/></>} />,
  settings:  (p: IconProps) => <I {...p} d={<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9.2a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9.2a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></>} />,
  chevronDown: (p: IconProps) => <I {...p} d={<path d="m6 9 6 6 6-6"/>} />,
  trash:     (p: IconProps) => <I {...p} d={<><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M6 6v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6"/><path d="M10 11v6M14 11v6"/></>} />,
  copy:      (p: IconProps) => <I {...p} d={<><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></>} />,
  key:       (p: IconProps) => <I {...p} d={<><circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.5 12.5 10-10"/><path d="m17 5 3 3"/><path d="m14 8 3 3"/></>} />,
};

// ---- Mono span + helpers -------------------------------------------------

export function Mono({
  children, dim, style, ...rest
}: { children: ReactNode; dim?: boolean; style?: CSSProperties } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span {...rest} style={{ fontFamily: "var(--font-mono)", color: dim ? "var(--fg-muted)" : undefined, ...style }}>
      {children}
    </span>
  );
}

export function relTime(input: string | number | null | undefined): string {
  if (!input || input === "—") return "—";
  let t: Date;
  if (typeof input === "number") {
    // epoch seconds
    t = new Date(input * 1000);
  } else {
    t = new Date(String(input).replace(" UTC", "Z").replace(" ", "T"));
  }
  if (isNaN(t.getTime())) return String(input);
  const diff = (Date.now() - t.getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
