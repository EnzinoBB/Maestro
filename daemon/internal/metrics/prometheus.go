package metrics

import (
	"context"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// PromTarget describes a single component-declared /metrics endpoint to scrape.
type PromTarget struct {
	ComponentID string
	URL         string   // full URL e.g. http://127.0.0.1:9100/metrics
	AllowList   []string // metric names we are allowed to ingest
}

// CollectPrometheus issues GET requests against each target and parses
// allow-listed metrics out of the Prometheus exposition format.
//
// Best-effort: any HTTP error or parse failure skips that target.
// The allow-list is enforced AFTER parsing so the scraper doesn't
// snowball if an exporter exposes thousands of series.
func CollectPrometheus(ctx context.Context, targets []PromTarget, timeout time.Duration) []Sample {
	if len(targets) == 0 {
		return nil
	}
	if timeout <= 0 {
		timeout = 3 * time.Second
	}
	client := &http.Client{Timeout: timeout}
	out := make([]Sample, 0, 16)
	for _, t := range targets {
		req, err := http.NewRequestWithContext(ctx, "GET", t.URL, nil)
		if err != nil {
			continue
		}
		resp, err := client.Do(req)
		if err != nil {
			continue
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != 200 {
			continue
		}
		allow := stringSet(t.AllowList)
		for _, s := range ParsePromExposition(string(body)) {
			if len(allow) > 0 {
				if _, ok := allow[s.MetricName]; !ok {
					continue
				}
			}
			out = append(out, Sample{
				Scope:   "component",
				ScopeID: t.ComponentID,
				Metric:  s.MetricName,
				Value:   s.Value,
			})
		}
	}
	return out
}

// PromSample is a single (metric, value) parsed from Prometheus exposition.
// Labels are deliberately ignored in M2.7 — the CP store doesn't model
// labels, and operators usually only care about the unlabeled or single
// label dimension. M2.8 may add label-aware ingestion.
type PromSample struct {
	MetricName string
	Value      float64
}

// ParsePromExposition parses Prometheus text-format metrics. Comment and
// HELP/TYPE lines are skipped; histograms/summaries are flattened to their
// sum/count buckets like any other line.
func ParsePromExposition(text string) []PromSample {
	out := make([]PromSample, 0, 32)
	for _, raw := range strings.Split(text, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		// "metric_name{labels} value [timestamp]"
		// Name: chars until '{' or whitespace.
		name := line
		if i := strings.IndexAny(line, "{ \t"); i > 0 {
			name = line[:i]
		}
		// Value: last whitespace-separated token (drop optional ts).
		toks := strings.Fields(line)
		if len(toks) < 2 {
			continue
		}
		valStr := toks[len(toks)-1]
		// If the last token looks like an integer timestamp, the value is
		// the second-to-last. We use a crude heuristic: any token > 1e10 is
		// probably a millisecond/microsecond timestamp.
		v, err := strconv.ParseFloat(valStr, 64)
		if err != nil {
			continue
		}
		if v > 1e10 && len(toks) >= 3 {
			vAlt, errAlt := strconv.ParseFloat(toks[len(toks)-2], 64)
			if errAlt == nil {
				v = vAlt
			}
		}
		out = append(out, PromSample{MetricName: name, Value: v})
	}
	return out
}

func stringSet(xs []string) map[string]struct{} {
	if len(xs) == 0 {
		return nil
	}
	m := make(map[string]struct{}, len(xs))
	for _, x := range xs {
		m[x] = struct{}{}
	}
	return m
}
