package metrics

import (
	"context"
	"os/exec"
	"strings"
)

// CollectLogRates returns log_lines_per_sec samples for each container
// in nameToCid, computed as (lines emitted in the last `windowSec` seconds) / windowSec.
//
// We shell out to `docker logs --since=<windowSec>s <name>` per container and
// count newlines. windowSec should match the metrics emission interval so
// the rate stays stable; defaults to 30s when <=0.
//
// Best-effort: any docker error skips that container without crashing.
func CollectLogRates(ctx context.Context, nameToCid map[string]string, windowSec int) []Sample {
	if len(nameToCid) == 0 {
		return nil
	}
	if windowSec <= 0 {
		windowSec = 30
	}
	out := make([]Sample, 0, len(nameToCid))
	for name, cid := range nameToCid {
		cmd := exec.CommandContext(ctx, "docker", "logs",
			"--since", itoaSec(windowSec),
			name,
		)
		raw, err := cmd.CombinedOutput()
		if err != nil {
			continue
		}
		count := strings.Count(string(raw), "\n")
		rate := float64(count) / float64(windowSec)
		out = append(out, Sample{
			Scope: "component", ScopeID: cid,
			Metric: "log_lines_per_sec", Value: rate,
		})
	}
	return out
}

func itoaSec(s int) string {
	// Avoid importing strconv just for this trivial case.
	if s == 30 {
		return "30s"
	}
	// Fall back via fmt.Sprintf-equivalent.
	digits := []byte{}
	if s == 0 {
		return "0s"
	}
	x := s
	for x > 0 {
		digits = append([]byte{byte('0' + x%10)}, digits...)
		x /= 10
	}
	return string(digits) + "s"
}
