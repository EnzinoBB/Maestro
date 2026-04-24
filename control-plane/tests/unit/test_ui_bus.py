import asyncio
import pytest

from app.ws.ui_bus import UIEventBus
from app.ws.protocol import make_message, T_EV_METRICS


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_subscribers():
    bus = UIEventBus()
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    unsub1 = bus.subscribe(q1.put_nowait)
    unsub2 = bus.subscribe(q2.put_nowait)

    await bus.broadcast({"type": "hub.event", "host_id": "h1", "event_type": "event.metrics",
                         "ts": 1.0, "summary": {"samples": 2, "events": 0}})

    f1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    f2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert f1 == f2
    assert f1["type"] == "hub.event"

    unsub1()
    unsub2()


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    bus = UIEventBus()
    q: asyncio.Queue = asyncio.Queue()
    unsub = bus.subscribe(q.put_nowait)
    unsub()
    await bus.broadcast({"type": "hub.event"})
    assert q.empty()


@pytest.mark.asyncio
async def test_handle_hub_event_summarizes_metrics_payload():
    bus = UIEventBus()
    seen: list[dict] = []
    bus.subscribe(seen.append)

    handler = bus.as_hub_handler()
    msg = make_message(T_EV_METRICS, {
        "samples": [{"scope": "host", "metric": "cpu_percent", "value": 10}] * 3,
        "events":  [{"kind": "x", "scope": "host", "scope_id": "h"}],
    })
    await handler("host1", msg)

    assert len(seen) == 1
    frame = seen[0]
    assert frame["type"] == "hub.event"
    assert frame["host_id"] == "host1"
    assert frame["event_type"] == "event.metrics"
    assert frame["summary"] == {"samples": 3, "events": 1}


@pytest.mark.asyncio
async def test_handle_hub_event_passes_through_non_metrics():
    bus = UIEventBus()
    seen: list[dict] = []
    bus.subscribe(seen.append)

    handler = bus.as_hub_handler()
    msg = make_message("event.status_change", {"to": "running"})
    await handler("host1", msg)

    assert len(seen) == 1
    assert seen[0]["event_type"] == "event.status_change"
    assert seen[0]["summary"] == {}
