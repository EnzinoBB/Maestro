"""Parser for the event.metrics WS payload."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..storage_metrics import MetricSample, MetricEvent


_VALID_SCOPES = {"host", "component", "deploy"}


@dataclass
class MetricsEvent:
    ts: float                  # epoch seconds
    host_id: str
    samples: list[MetricSample] = field(default_factory=list)
    events: list[MetricEvent] = field(default_factory=list)


def _parse_ts(raw: Any) -> float:
    if raw is None:
        return time.time()
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()
    return time.time()


def parse_metrics_event(payload: dict[str, Any]) -> MetricsEvent:
    """Permissive parser. Drops malformed entries silently so an evolving
    daemon can add new metrics without crashing the CP."""
    ts = _parse_ts(payload.get("ts"))
    host_id = str(payload.get("host_id", "") or "")

    samples: list[MetricSample] = []
    for s in payload.get("samples") or []:
        try:
            scope = str(s.get("scope", ""))
            if scope not in _VALID_SCOPES:
                continue
            scope_id = str(s.get("scope_id", ""))
            metric = str(s.get("metric", ""))
            if not scope_id or not metric:
                continue
            v = s.get("value")
            if isinstance(v, bool):
                v = 1.0 if v else 0.0
            elif not isinstance(v, (int, float)):
                continue
            samples.append(MetricSample(
                ts=ts, scope=scope, scope_id=scope_id, metric=metric, value=float(v),
            ))
        except (AttributeError, TypeError):
            continue

    events: list[MetricEvent] = []
    for e in payload.get("events") or []:
        try:
            scope = str(e.get("scope", ""))
            if scope not in _VALID_SCOPES:
                continue
            scope_id = str(e.get("scope_id", ""))
            kind = str(e.get("kind", ""))
            if not scope_id or not kind:
                continue
            ev_payload = e.get("payload")
            if ev_payload is not None and not isinstance(ev_payload, dict):
                continue
            events.append(MetricEvent(
                ts=ts, kind=kind, scope=scope, scope_id=scope_id, payload=ev_payload,
            ))
        except (AttributeError, TypeError):
            continue

    return MetricsEvent(ts=ts, host_id=host_id, samples=samples, events=events)
