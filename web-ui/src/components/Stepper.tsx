import { Fragment } from "react";
import { Icons } from "../primitives";

/**
 * Compact horizontal stepper used by EnrollDrawer + SetupWelcome.
 *
 * Active step gets the teal accent + bold label, completed steps get a
 * filled OK background with a check, future steps stay dim.
 */
export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="hstack" style={{
      gap: 0, padding: "12px 18px",
      borderBottom: "1px solid var(--border)", background: "var(--bg-2)",
    }}>
      {steps.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <Fragment key={i}>
            <div className="hstack" style={{ gap: 8, opacity: active || done ? 1 : 0.5 }}>
              <div style={{
                width: 22, height: 22, borderRadius: 999,
                display: "grid", placeItems: "center",
                fontSize: 10, fontWeight: 600, fontFamily: "var(--font-mono)",
                background: done ? "var(--ok)" : active ? "var(--accent)" : "var(--bg-3)",
                color: done || active ? "var(--bg)" : "var(--fg-muted)",
                border: active ? "2px solid color-mix(in oklch, var(--accent) 30%, transparent)" : "none",
              }}>
                {done ? <Icons.check size={11} /> : i + 1}
              </div>
              <span style={{ fontSize: 12, fontWeight: active ? 600 : 400 }}>{s}</span>
            </div>
            {i < steps.length - 1 &&
              <div style={{ flex: 1, height: 1, background: "var(--border)", margin: "0 12px" }} />
            }
          </Fragment>
        );
      })}
    </div>
  );
}
