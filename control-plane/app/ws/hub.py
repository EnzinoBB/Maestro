"""Hub: registry of connected daemons + request/response routing."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

from .protocol import Message, make_message, T_HELLO, T_PING, T_PONG

log = logging.getLogger("maestro.hub")


class DaemonOffline(Exception):
    pass


class RequestTimeout(Exception):
    pass


EventHandler = Callable[[str, Message], Awaitable[None]]
RegisterHandler = Callable[["DaemonConnection"], Awaitable[None]]


@dataclass
class DaemonConnection:
    host_id: str
    websocket: WebSocket
    daemon_version: str = ""
    runners: list[str] = field(default_factory=list)
    components_known: list[dict] = field(default_factory=list)
    connected_at: float = field(default_factory=time.time)
    system: dict = field(default_factory=dict)
    # Optional claim sent at connect time; the auto-register handler uses
    # this as the owner_user_id when creating a fresh `node` row, so a
    # daemon enrolled by a non-admin operator becomes their personal node
    # rather than defaulting to the first admin.
    claim_user_id: str | None = None
    _pending: dict[str, asyncio.Future] = field(default_factory=dict)
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _closed: bool = False

    async def send(self, msg: Message) -> None:
        if self._closed:
            raise DaemonOffline(f"daemon {self.host_id} offline")
        async with self._send_lock:
            await self.websocket.send_text(json.dumps(msg.to_json()))

    def close(self) -> None:
        self._closed = True
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(DaemonOffline(f"daemon {self.host_id} disconnected"))
        self._pending.clear()


class Hub:
    def __init__(self) -> None:
        self._conns: dict[str, DaemonConnection] = {}
        self._event_handlers: list[EventHandler] = []
        self._register_handlers: list[RegisterHandler] = []
        self._lock = asyncio.Lock()

    # ---- connection lifecycle -------------------------------------------

    async def register(self, conn: DaemonConnection) -> None:
        async with self._lock:
            old = self._conns.get(conn.host_id)
            if old is not None:
                old.close()
            self._conns[conn.host_id] = conn
        log.info("daemon registered: %s", conn.host_id)
        for h in self._register_handlers:
            try:
                await h(conn)
            except Exception:
                log.exception("register handler failed for %s", conn.host_id)

    def add_register_handler(self, h: RegisterHandler) -> None:
        self._register_handlers.append(h)

    async def unregister(self, host_id: str) -> None:
        async with self._lock:
            conn = self._conns.pop(host_id, None)
        if conn is not None:
            conn.close()
            log.info("daemon unregistered: %s", host_id)

    def list_hosts(self) -> list[dict]:
        out = []
        for hid, c in self._conns.items():
            out.append({
                "host_id": hid,
                "daemon_version": c.daemon_version,
                "runners": c.runners,
                "connected_at": c.connected_at,
                "online": not c._closed,
                "system": c.system,
            })
        return out

    def is_online(self, host_id: str) -> bool:
        c = self._conns.get(host_id)
        return c is not None and not c._closed

    # ---- request/response ------------------------------------------------

    async def request(
        self,
        host_id: str,
        type_: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> Message:
        conn = self._conns.get(host_id)
        if conn is None or conn._closed:
            raise DaemonOffline(f"daemon {host_id} is not connected")

        msg = make_message(type_, payload or {})
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        conn._pending[msg.id] = fut
        try:
            await conn.send(msg)
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            raise RequestTimeout(f"no response to {type_} within {timeout}s") from e
        finally:
            conn._pending.pop(msg.id, None)

    # ---- event fan-out ---------------------------------------------------

    def add_event_handler(self, h: EventHandler) -> None:
        self._event_handlers.append(h)

    async def _emit(self, host_id: str, msg: Message) -> None:
        for h in self._event_handlers:
            try:
                await h(host_id, msg)
            except Exception:
                log.exception("event handler failed")

    # ---- main receive loop, driven by FastAPI endpoint -------------------

    async def _recv_loop(self, conn: DaemonConnection) -> None:
        try:
            while True:
                raw = await conn.websocket.receive_text()
                try:
                    data = json.loads(raw)
                    msg = Message.model_validate(data)
                except Exception:
                    log.warning("invalid message from %s: %s", conn.host_id, raw[:200])
                    continue

                if msg.type == T_PING:
                    await conn.send(make_message(T_PONG, id_=msg.id))
                    continue
                if msg.type == T_PONG:
                    continue

                if msg.in_reply_to:
                    fut = conn._pending.get(msg.in_reply_to)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                    continue

                if msg.type.startswith("event."):
                    await self._emit(conn.host_id, msg)
                    continue

                log.debug("unroutable message from %s: type=%s id=%s",
                          conn.host_id, msg.type, msg.id)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("recv loop crash for %s", conn.host_id)

    async def _heartbeat_loop(self, conn: DaemonConnection, interval: int) -> None:
        try:
            while not conn._closed:
                await asyncio.sleep(interval)
                try:
                    await conn.send(make_message(T_PING))
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def handle_daemon_ws(
        self, websocket: WebSocket, host_id: str, token: str | None,
        *, expected_token: str | None = None, heartbeat_interval: int = 15,
        claim_user_id: str | None = None,
    ) -> None:
        if expected_token is not None and token != expected_token:
            await websocket.close(code=4401)
            return

        await websocket.accept()

        # Control-plane sends hello first
        hello = make_message(T_HELLO, {
            "server_version": "0.1.0",
            "assigned_host_id": host_id,
            "heartbeat_interval_sec": heartbeat_interval,
            "session_id": f"s-{uuid.uuid4().hex[:10]}",
        })
        await websocket.send_text(json.dumps(hello.to_json()))

        # Expect hello_ack
        ack_raw = await websocket.receive_text()
        try:
            ack = Message.model_validate(json.loads(ack_raw))
        except Exception:
            await websocket.close(code=4400)
            return
        if ack.type != "hello_ack":
            await websocket.close(code=4400)
            return

        conn = DaemonConnection(
            host_id=host_id,
            websocket=websocket,
            daemon_version=str(ack.payload.get("daemon_version", "")),
            runners=list(ack.payload.get("runners_available", [])),
            components_known=list(ack.payload.get("components_known", [])),
            system=dict(ack.payload.get("system", {})),
            claim_user_id=claim_user_id,
        )
        await self.register(conn)

        hb_task = asyncio.create_task(self._heartbeat_loop(conn, heartbeat_interval))
        try:
            await self._recv_loop(conn)
        finally:
            hb_task.cancel()
            await self.unregister(host_id)
