"""Stable component-set hashing for deploy versioning."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def components_hash_from_rendered(rendered: dict[tuple[str, str], dict[str, Any]]) -> str:
    """SHA256 over the sorted sequence of (host, component_id, component_hash).

    We include only (host, component_id, component_hash) so the hash is stable
    against non-material payload fields. `component_hash` is the per-component
    hash computed by the renderer (already includes config_archives content).
    """
    items = sorted(
        (host, cid, (payload or {}).get("component_hash", ""))
        for (host, cid), payload in rendered.items()
    )
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
