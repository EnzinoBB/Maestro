package metrics

import (
	"context"
	"os/exec"
	"strconv"
	"strings"
)

// ParseDockerStats parses output from
//
//	docker stats --no-stream --format "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}"
//
// and produces samples keyed by component_id (via nameToCid mapping).
// Containers not present in nameToCid are dropped so other Docker
// containers on the host don't leak into the CP's metrics store.
func ParseDockerStats(out string, nameToCid map[string]string) []Sample {
	samples := make([]Sample, 0, len(nameToCid)*2)
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.Split(line, "|")
		if len(parts) != 3 {
			continue
		}
		name := strings.TrimSpace(parts[0])
		if name == "" {
			continue
		}
		cid, ok := nameToCid[name]
		if !ok {
			continue
		}
		cpu, cpuOk := parsePercent(parts[1])
		ram, ramOk := parsePercent(parts[2])
		if cpuOk {
			samples = append(samples, Sample{
				Scope: "component", ScopeID: cid,
				Metric: "container_cpu_percent", Value: cpu,
			})
		}
		if ramOk {
			samples = append(samples, Sample{
				Scope: "component", ScopeID: cid,
				Metric: "container_ram_percent", Value: ram,
			})
		}
	}
	return samples
}

func parsePercent(s string) (float64, bool) {
	s = strings.TrimSpace(s)
	s = strings.TrimSuffix(s, "%")
	if s == "" {
		return 0, false
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0, false
	}
	return v, true
}

// CollectDocker runs the docker CLI and returns samples for each container
// in `nameToCid`. Returns nil if docker is unavailable or fails — the
// caller treats metrics as best-effort.
func CollectDocker(ctx context.Context, nameToCid map[string]string) []Sample {
	if len(nameToCid) == 0 {
		return nil
	}
	cmd := exec.CommandContext(ctx, "docker", "stats", "--no-stream",
		"--format", "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}")
	out, err := cmd.Output()
	if err != nil {
		return nil
	}
	return ParseDockerStats(string(out), nameToCid)
}
