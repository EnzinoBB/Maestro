"""Hub event handler that persists incoming event.metrics envelopes."""
from __future__ import annotations

from typing import Awaitable, Callable

from ..storage_metrics import MetricsRepository
from ..ws.protocol import Message, T_EV_METRICS
from .contract import parse_metrics_event


EventHandler = Callable[[str, Message], Awaitable[None]]


def make_metrics_event_handler(repo: MetricsRepository) -> EventHandler:
    """Returns a Hub-compatible event handler.

    Side effect: persists samples + events from incoming `event.metrics`
    messages. Other event types pass through unchanged.

    A subtle convenience: for host-scoped samples that omit `scope_id`,
    we substitute the WS origin's `host_id` so daemons can stay terse.
    The contract parser drops samples with empty scope_id; we therefore
    fix them up *before* calling the parser.
    """
    async def handle(host_id: str, msg: Message) -> None:
        if msg.type != T_EV_METRICS:
            return
        payload = dict(msg.payload or {})
        samples_in = payload.get("samples") or []
        fixed_samples = []
        for s in samples_in:
            if isinstance(s, dict) and s.get("scope") == "host" and not s.get("scope_id"):
                s = {**s, "scope_id": host_id}
            fixed_samples.append(s)
        payload["samples"] = fixed_samples
        if not payload.get("host_id"):
            payload["host_id"] = host_id

        ev = parse_metrics_event(payload)
        if ev.samples:
            await repo.record_samples(list(ev.samples))
        for me in ev.events:
            await repo.record_event(me)

    return handle
