import { Mono } from "../primitives";

/**
 * 4-bar strength meter shared by Add user / Change password / Setup welcome.
 *
 * Score buckets (heuristic, deliberately gentle):
 *   0 — too weak  (less than 8 chars OR < 2 character classes)
 *   1 — weak      (8+ chars, 2+ classes)
 *   2 — ok        (10+ chars, 3+ classes)
 *   3 — strong    (12+ chars, 3+ classes)
 *
 * Doesn't enforce; the API enforces "8+ chars" and accepts the rest.
 */
export function PasswordStrength({ value }: { value: string }) {
  const len = value.length;
  const classes =
    (/[a-z]/.test(value) ? 1 : 0) +
    (/[A-Z]/.test(value) ? 1 : 0) +
    (/\d/.test(value) ? 1 : 0) +
    (/[^A-Za-z0-9]/.test(value) ? 1 : 0);
  let score = 0;
  if (len >= 8 && classes >= 2) score = 1;
  if (len >= 10 && classes >= 3) score = 2;
  if (len >= 12 && classes >= 3) score = 3;
  const colors = ["var(--err)", "var(--warn)", "oklch(0.78 0.14 130)", "var(--ok)"];
  const labels = ["too weak", "weak", "ok", "strong"];
  return (
    <div className="hstack" style={{ gap: 8, marginTop: 6 }}>
      <div style={{ display: "flex", gap: 3, flex: 1 }}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} style={{
            flex: 1, height: 4, borderRadius: 2,
            background: i <= score ? colors[score] : "var(--bg-3)",
          }} />
        ))}
      </div>
      <span className="mono small" style={{ color: colors[score], minWidth: 56, textAlign: "right" }}>
        {labels[score]}
      </span>
      <Mono dim style={{ fontSize: 11, minWidth: 36, textAlign: "right" }}>
        {len}/8+
      </Mono>
    </div>
  );
}
