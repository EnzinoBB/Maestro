"""Compute desired vs observed diff per component."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def component_hash(rendered_payload: dict[str, Any]) -> str:
    """Stable hash of the rendered component spec (build+run+config+source).

    For config_archives we include only {dest, strategy, mode, content_hash} and
    skip tar_b64 — content_hash is already sha256(tar_bytes) so including the
    blob again would bloat the hash input for no information gain.
    """
    keys = ["source", "build_steps", "config_files", "run", "healthcheck"]
    sub = {k: rendered_payload.get(k) for k in keys}
    archives = rendered_payload.get("config_archives") or []
    sub["config_archives"] = [
        {"dest": a.get("dest"), "strategy": a.get("strategy"),
         "mode": a.get("mode"), "content_hash": a.get("content_hash")}
        for a in archives
    ]
    return hashlib.sha256(
        json.dumps(sub, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]


@dataclass
class ComponentChange:
    component_id: str
    host_id: str
    action: str                      # create | update | remove | unchanged
    old_hash: str | None = None
    new_hash: str | None = None

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "host_id": self.host_id,
            "action": self.action,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
        }


@dataclass
class Diff:
    changes: list[ComponentChange] = field(default_factory=list)

    @property
    def to_create(self): return [c for c in self.changes if c.action == "create"]
    @property
    def to_update(self): return [c for c in self.changes if c.action == "update"]
    @property
    def to_remove(self): return [c for c in self.changes if c.action == "remove"]
    @property
    def unchanged(self): return [c for c in self.changes if c.action == "unchanged"]

    @property
    def has_changes(self) -> bool:
        return any(c.action in ("create", "update", "remove") for c in self.changes)

    def to_dict(self) -> dict:
        return {
            "changes": [c.to_dict() for c in self.changes],
            "summary": {
                "create": len(self.to_create),
                "update": len(self.to_update),
                "remove": len(self.to_remove),
                "unchanged": len(self.unchanged),
            },
        }


def compute_diff(
    desired: dict[tuple[str, str], dict[str, Any]],   # (host_id, component_id) -> payload
    observed: dict[tuple[str, str], str | None],      # (host_id, component_id) -> hash
) -> Diff:
    changes: list[ComponentChange] = []

    # create or update
    for (hid, cid), payload in desired.items():
        new = component_hash(payload)
        old = observed.get((hid, cid))
        if old is None:
            changes.append(ComponentChange(cid, hid, "create", None, new))
        elif old != new:
            changes.append(ComponentChange(cid, hid, "update", old, new))
        else:
            changes.append(ComponentChange(cid, hid, "unchanged", old, new))

    # remove: observed keys not present in desired
    for (hid, cid), old in observed.items():
        if (hid, cid) not in desired:
            changes.append(ComponentChange(cid, hid, "remove", old, None))

    return Diff(changes=changes)
