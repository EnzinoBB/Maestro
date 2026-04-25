package metrics

import (
	"context"
	"runtime"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/load"
	"github.com/shirou/gopsutil/v3/mem"
)

// Sample is the wire format the orchestrator emits for each measurement.
type Sample struct {
	Scope   string  `json:"scope"`
	ScopeID string  `json:"scope_id"`
	Metric  string  `json:"metric"`
	Value   float64 `json:"value"`
}

// CollectHost returns CPU%, RAM%, and 1-minute load for the local host.
// On platforms where load average is unavailable (Windows), load1 is omitted.
func CollectHost(ctx context.Context) []Sample {
	out := make([]Sample, 0, 3)

	// CPU: 200ms blocking sample. Acceptable inside a 30s ticker.
	cpuCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()
	if pcts, err := cpu.PercentWithContext(cpuCtx, 200*time.Millisecond, false); err == nil && len(pcts) > 0 {
		out = append(out, Sample{Scope: "host", Metric: "cpu_percent", Value: pcts[0]})
	}

	if vm, err := mem.VirtualMemory(); err == nil {
		out = append(out, Sample{Scope: "host", Metric: "ram_percent", Value: vm.UsedPercent})
	}

	if runtime.GOOS != "windows" {
		if l, err := load.Avg(); err == nil {
			out = append(out, Sample{Scope: "host", Metric: "load1", Value: l.Load1})
		}
	}
	return out
}
