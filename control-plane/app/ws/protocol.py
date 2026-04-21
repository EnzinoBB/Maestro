"""WebSocket message envelope and helpers (control-plane ↔ daemon)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    in_reply_to: str | None = None
    ts: str | None = None

    def to_json(self) -> dict[str, Any]:
        d = self.model_dump(exclude_none=True)
        return d


def make_message(type_: str, payload: dict[str, Any] | None = None,
                 *, in_reply_to: str | None = None, id_: str | None = None) -> Message:
    return Message(
        id=id_ or f"ctl-{uuid.uuid4().hex[:12]}",
        type=type_,
        payload=payload or {},
        in_reply_to=in_reply_to,
        ts=_now_iso(),
    )


# Standard type constants
T_HELLO = "hello"
T_HELLO_ACK = "hello_ack"
T_BYE = "bye"
T_PING = "ping"
T_PONG = "pong"

T_REQ_STATE_GET = "request.state.get"
T_RES_STATE_GET = "response.state.get"
T_REQ_DEPLOY = "request.deploy"
T_RES_DEPLOY = "response.deploy"
T_REQ_START = "request.start"
T_RES_START = "response.start"
T_REQ_STOP = "request.stop"
T_RES_STOP = "response.stop"
T_REQ_RESTART = "request.restart"
T_RES_RESTART = "response.restart"
T_REQ_LOGS_TAIL = "request.logs.tail"
T_RES_LOGS_TAIL = "response.logs.tail"
T_REQ_HEALTH = "request.healthcheck.run"
T_RES_HEALTH = "response.healthcheck.run"

T_EV_STATUS_CHANGE = "event.status_change"
T_EV_METRICS = "event.metrics"
T_EV_HEALTH_FAILED = "event.healthcheck_failed"
