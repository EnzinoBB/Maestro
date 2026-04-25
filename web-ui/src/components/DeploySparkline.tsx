import { useMetricRange } from "../api/client";
import { Sparkline } from "../primitives";

/**
 * Small sparkline slot for overview cards. Takes a representative
 * componentId (for now, the first component in the deploy's current
 * YAML) and shows its container CPU series. Degrades to a terse
 * "no samples yet" label when data is absent so the layout stays
 * stable.
 *
 * When M3 ships a structured components list on the deploy API, the
 * caller will pass a real component_id; until then callers pass null
 * and we render the placeholder.
 */
export function DeploySparkline({ componentId }: { componentId: string | null }) {
  const enabled = !!componentId;
  const { data } = useMetricRange(
    "component", componentId || "", "container_cpu_percent",
    15 * 60, enabled,
  );
  const series = (data || []).map(([t, v]) => ({ t, v }));
  if (!enabled || series.length === 0) {
    return (
      <div className="small dim" style={{ height: 30, display: "flex", alignItems: "center" }}>
        no samples yet
      </div>
    );
  }
  return <Sparkline data={series} width={280} height={30} />;
}
