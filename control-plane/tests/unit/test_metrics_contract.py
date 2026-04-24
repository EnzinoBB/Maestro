from app.metrics.contract import parse_metrics_event, MetricsEvent


def test_parse_full_payload():
    payload = {
        "ts": "2026-04-24T11:34:00Z",
        "host_id": "host1",
        "samples": [
            {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": 42.0},
            {"scope": "component", "scope_id": "web", "metric": "healthcheck_latency_ms", "value": 23.4},
        ],
        "events": [
            {"kind": "healthcheck_state_change", "scope": "component", "scope_id": "web",
             "payload": {"from": "ok", "to": "fail"}},
        ],
    }
    parsed = parse_metrics_event(payload)
    assert isinstance(parsed, MetricsEvent)
    assert parsed.ts > 0
    assert parsed.host_id == "host1"
    assert len(parsed.samples) == 2
    assert parsed.samples[0].metric == "cpu_percent"
    assert parsed.samples[0].value == 42.0
    assert len(parsed.events) == 1
    assert parsed.events[0].kind == "healthcheck_state_change"


def test_parse_drops_unknown_scope_silently():
    payload = {
        "ts": "2026-04-24T11:34:00Z",
        "host_id": "host1",
        "samples": [
            {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": 10},
            {"scope": "WHATEVER", "scope_id": "x", "metric": "y", "value": 1},
        ],
    }
    parsed = parse_metrics_event(payload)
    assert len(parsed.samples) == 1


def test_parse_skips_non_numeric_values():
    payload = {
        "ts": "2026-04-24T11:34:00Z",
        "host_id": "host1",
        "samples": [
            {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": "not a number"},
            {"scope": "host", "scope_id": "host1", "metric": "load1", "value": 1.5},
        ],
    }
    parsed = parse_metrics_event(payload)
    assert len(parsed.samples) == 1
    assert parsed.samples[0].metric == "load1"


def test_parse_missing_ts_uses_now():
    import time
    before = time.time()
    parsed = parse_metrics_event({"host_id": "h", "samples": []})
    assert parsed.ts >= before


def test_parse_missing_host_id_returns_empty_host_id():
    parsed = parse_metrics_event({"samples": []})
    assert parsed.host_id == ""
