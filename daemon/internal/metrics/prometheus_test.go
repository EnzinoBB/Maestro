package metrics

import "testing"

func TestParsePromExposition_PlainGauges(t *testing.T) {
	text := `# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total 12345
process_cpu_seconds_total 42.5
`
	samples := ParsePromExposition(text)
	if len(samples) != 2 {
		t.Fatalf("expected 2 samples, got %d", len(samples))
	}
	if samples[0].MetricName != "http_requests_total" || samples[0].Value != 12345 {
		t.Errorf("got %+v", samples[0])
	}
	if samples[1].MetricName != "process_cpu_seconds_total" || samples[1].Value != 42.5 {
		t.Errorf("got %+v", samples[1])
	}
}

func TestParsePromExposition_SkipsBadLines(t *testing.T) {
	text := `

# comment
not_enough_fields
metric_a 1.5
metric_b not-a-number
`
	samples := ParsePromExposition(text)
	if len(samples) != 1 {
		t.Fatalf("expected 1 sample, got %d", len(samples))
	}
	if samples[0].MetricName != "metric_a" {
		t.Errorf("got %q", samples[0].MetricName)
	}
}


func TestParsePromExposition_LabeledMetric(t *testing.T) {
	text := `http_requests{method="GET",status="200"} 7
`
	samples := ParsePromExposition(text)
	if len(samples) != 1 || samples[0].MetricName != "http_requests" || samples[0].Value != 7 {
		t.Fatalf("got %+v", samples)
	}
}

func TestParsePromExposition_TimestampStripped(t *testing.T) {
	// Last token > 1e10 looks like an ms timestamp; the value should fall back
	// to the second-to-last token.
	text := `metric_x 99 1620000000000
`
	samples := ParsePromExposition(text)
	if len(samples) != 1 || samples[0].Value != 99 {
		t.Fatalf("got %+v", samples)
	}
}
