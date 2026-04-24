"""Background task that periodically prunes old metric samples + events."""
from __future__ import annotations

import asyncio
import logging

from ..storage_metrics import MetricsRepository

log = logging.getLogger("maestro.metrics.retention")


async def retention_loop(
    repo: MetricsRepository,
    *,
    interval_seconds: int = 600,
    samples_max_age_seconds: int = 24 * 3600,
    events_keep_last_n: int = 10_000,
) -> None:
    """Run forever (until cancelled). One pass every `interval_seconds`.

    Defaults: samples retained 24h; events capped at 10k rows.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
        try:
            await repo.cleanup_older_than(
                samples_max_age_seconds=samples_max_age_seconds,
                events_keep_last_n=events_keep_last_n,
            )
        except Exception:
            log.exception("retention pass failed")
