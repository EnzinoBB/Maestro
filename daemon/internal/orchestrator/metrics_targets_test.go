package orchestrator

import (
	"testing"

	"github.com/maestro-project/maestro-daemon/internal/state"
)

func TestPromTargetsFromComps_FiltersAndSplitsAllow(t *testing.T) {
	comps := []*state.Component{
		{ID: "web", MetricsEndpoint: "http://127.0.0.1:9100/metrics",
			MetricsAllow: "http_requests_total, process_cpu_seconds_total"},
		{ID: "noop", MetricsEndpoint: "", MetricsAllow: ""},
		{ID: "api", MetricsEndpoint: "http://127.0.0.1:9101/metrics",
			MetricsAllow: "queue_depth"},
	}
	got := promTargetsFromComps(comps)
	if len(got) != 2 {
		t.Fatalf("expected 2 targets (web, api), got %d", len(got))
	}
	// web target
	if got[0].ComponentID != "web" || got[0].URL != "http://127.0.0.1:9100/metrics" {
		t.Errorf("web wrong: %+v", got[0])
	}
	if len(got[0].AllowList) != 2 ||
		got[0].AllowList[0] != "http_requests_total" ||
		got[0].AllowList[1] != "process_cpu_seconds_total" {
		t.Errorf("web allow wrong: %+v", got[0].AllowList)
	}
	// api target
	if got[1].ComponentID != "api" || len(got[1].AllowList) != 1 ||
		got[1].AllowList[0] != "queue_depth" {
		t.Errorf("api wrong: %+v", got[1])
	}
}

func TestPromTargetsFromComps_EmptyAllowProducesEmptySlice(t *testing.T) {
	comps := []*state.Component{
		{ID: "web", MetricsEndpoint: "http://x/metrics", MetricsAllow: ""},
	}
	got := promTargetsFromComps(comps)
	if len(got) != 1 {
		t.Fatalf("expected 1 target, got %d", len(got))
	}
	if got[0].AllowList != nil && len(got[0].AllowList) != 0 {
		t.Errorf("expected empty allow list, got %+v", got[0].AllowList)
	}
}

func TestPromTargetsFromComps_NoComps(t *testing.T) {
	if got := promTargetsFromComps(nil); len(got) != 0 {
		t.Errorf("expected empty, got %+v", got)
	}
}
