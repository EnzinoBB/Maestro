package metrics

import (
	"context"
	"testing"
)

func TestCollectHostReturnsAtLeastOneSample(t *testing.T) {
	samples := CollectHost(context.Background())
	if len(samples) == 0 {
		t.Fatalf("expected at least one host sample, got 0")
	}
	for _, s := range samples {
		if s.Scope != "host" {
			t.Errorf("expected scope=host, got %q", s.Scope)
		}
		if s.Metric == "" {
			t.Error("metric name must be non-empty")
		}
	}
}
