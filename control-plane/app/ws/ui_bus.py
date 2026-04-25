"""In-process pub/sub that fans Hub events out to browser WebSocket clients."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .protocol import Message, T_EV_METRICS

log = logging.getLogger("maestro.ui_bus")


Subscriber = Callable[[dict[str, Any]], None]
HubEventHandler = Callable[[str, Message], Awaitable[None]]


class UIEventBus:
    """Fan-out for a tiny set of browser subscribers.

    Subscribers receive summarized JSON-able frames. They must be cheap,
    non-blocking callables (e.g. `asyncio.Queue.put_nowait`). We never
    block the broadcaster on slow clients — if a queue is full, that
    subscriber's callable can raise; the exception is logged and swallowed.
    """

    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subs.add(fn)
        def _unsub() -> None:
            self._subs.discard(fn)
        return _unsub

    async def broadcast(self, frame: dict[str, Any]) -> None:
        for fn in list(self._subs):
            try:
                fn(frame)
            except Exception:
                log.exception("ui_bus subscriber failed (dropping frame for that sub)")

    def as_hub_handler(self) -> HubEventHandler:
        """Return a Hub-compatible event handler that summarizes the envelope
        and broadcasts. No payload contents are leaked — only counts."""
        async def handle(host_id: str, msg: Message) -> None:
            summary: dict[str, Any] = {}
            if msg.type == T_EV_METRICS:
                payload = msg.payload or {}
                samples = payload.get("samples") or []
                events = payload.get("events") or []
                summary = {
                    "samples": len(samples) if isinstance(samples, list) else 0,
                    "events": len(events) if isinstance(events, list) else 0,
                }
            frame = {
                "type": "hub.event",
                "host_id": host_id,
                "event_type": msg.type,
                "ts": msg.ts,
                "summary": summary,
            }
            await self.broadcast(frame)
        return handle
