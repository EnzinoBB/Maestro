import { useRecentFrames } from "../hooks/useRealtime";

/**
 * Compact topbar strip that surfaces the latest WS event so the operator
 * can tell the system is alive. Mirrors the Claude Design prototype's
 * "ticker" primitive (class `cp-ticker`) fed by real bus frames.
 */
export function Ticker() {
  const frames = useRecentFrames(1);
  const f = frames[0];
  if (!f || f.type !== "hub.event") {
    return (
      <div className="cp-ticker">
        <span className="cp-ticker__label">events</span>
        <span className="cp-ticker__msg dim">idle</span>
      </div>
    );
  }
  const when = typeof f.ts === "number"
    ? new Date(f.ts * 1000).toLocaleTimeString()
    : new Date(String(f.ts)).toLocaleTimeString();
  const counts = f.summary
    ? Object.entries(f.summary).map(([k, v]) => `${k}=${v}`).join(" ")
    : "";
  return (
    <div className="cp-ticker" title={`${f.event_type} from ${f.host_id}`}>
      <span className="cp-ticker__label">{when}</span>
      <span className="cp-ticker__msg">
        {f.host_id} · {f.event_type}{counts ? ` · ${counts}` : ""}
      </span>
    </div>
  );
}
