package metrics

import (
	"testing"
)

func TestParseDockerStats_HappyPath(t *testing.T) {
	out := "maestro-web|12.50%|34.10%\nmaestro-api|7.20%|18.90%\nother-thing|99.00%|99.00%\n"
	nameToCid := map[string]string{
		"maestro-web": "web",
		"maestro-api": "api",
	}
	samples := ParseDockerStats(out, nameToCid)
	if len(samples) != 4 {
		t.Fatalf("expected 4 samples (2 containers × 2 metrics), got %d", len(samples))
	}
	got := map[string]float64{}
	for _, s := range samples {
		got[s.ScopeID+"|"+s.Metric] = s.Value
	}
	if v := got["web|container_cpu_percent"]; v != 12.5 {
		t.Errorf("web cpu: got %v want 12.5", v)
	}
	if v := got["web|container_ram_percent"]; v != 34.1 {
		t.Errorf("web ram: got %v want 34.1", v)
	}
	if v := got["api|container_cpu_percent"]; v != 7.2 {
		t.Errorf("api cpu: got %v want 7.2", v)
	}
	if v := got["api|container_ram_percent"]; v != 18.9 {
		t.Errorf("api ram: got %v want 18.9", v)
	}
}

func TestParseDockerStats_IgnoresUnknownContainers(t *testing.T) {
	out := "unrelated|50.00%|50.00%\n"
	samples := ParseDockerStats(out, map[string]string{"maestro-web": "web"})
	if len(samples) != 0 {
		t.Fatalf("unknown container should produce 0 samples, got %d", len(samples))
	}
}

func TestParseDockerStats_SkipsMalformedLines(t *testing.T) {
	out := "good|1.00%|2.00%\ngarbage\n|empty|\n"
	samples := ParseDockerStats(out, map[string]string{"good": "c1"})
	if len(samples) != 2 {
		t.Fatalf("expected 2 samples from 1 good line, got %d", len(samples))
	}
}

func TestParseDockerStats_HandlesEmptyInput(t *testing.T) {
	samples := ParseDockerStats("", map[string]string{"x": "y"})
	if len(samples) != 0 {
		t.Fatalf("empty input must yield no samples")
	}
}
