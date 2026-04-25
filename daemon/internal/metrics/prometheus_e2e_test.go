package metrics

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// End-to-end: spin up a real HTTP server that returns Prometheus exposition,
// run CollectPrometheus against it, assert the returned samples are filtered
// by the allow-list and labelled with the component id.
func TestCollectPrometheus_E2E_AllowListEnforced(t *testing.T) {
	body := `# HELP http_requests_total ...
# TYPE http_requests_total counter
http_requests_total{method="GET"} 42
http_requests_total{method="POST"} 7
process_cpu_seconds_total 12.5
internal_secret_metric 999
`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, body)
	}))
	defer srv.Close()

	targets := []PromTarget{{
		ComponentID: "web",
		URL:         srv.URL + "/metrics",
		AllowList:   []string{"http_requests_total", "process_cpu_seconds_total"},
	}}
	samples := CollectPrometheus(context.Background(), targets, 2*time.Second)

	// We expect two http_requests_total lines (different labels parse to same name)
	// + one process_cpu_seconds_total. internal_secret_metric is dropped.
	wantNames := map[string]int{
		"http_requests_total":       2,
		"process_cpu_seconds_total": 1,
	}
	gotNames := map[string]int{}
	for _, s := range samples {
		if s.Scope != "component" || s.ScopeID != "web" {
			t.Errorf("wrong scope: %+v", s)
		}
		gotNames[s.Metric]++
		if s.Metric == "internal_secret_metric" {
			t.Errorf("disallowed metric leaked: %+v", s)
		}
	}
	for name, n := range wantNames {
		if gotNames[name] != n {
			t.Errorf("metric %q: got %d, want %d", name, gotNames[name], n)
		}
	}
}

func TestCollectPrometheus_E2E_BadServerReturnsEmpty(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(500)
	}))
	defer srv.Close()
	out := CollectPrometheus(context.Background(),
		[]PromTarget{{ComponentID: "x", URL: srv.URL, AllowList: []string{"any"}}},
		2*time.Second)
	if len(out) != 0 {
		t.Errorf("expected empty on 500, got %d", len(out))
	}
}
