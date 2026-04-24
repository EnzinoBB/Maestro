"""One-time migration from pre-M1 single-config-row to multi-deploy schema."""
from __future__ import annotations

import aiosqlite


async def migrate_legacy_config_to_default_deploy(db_path: str) -> None:
    """If a legacy `config` row exists and no `default` deploy has been created
    yet, materialize the legacy YAML as deploy 'default' owned by 'singleuser'.

    Idempotent: running multiple times has no effect after the first run.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        async with db.execute(
            "SELECT id FROM deploys WHERE owner_user_id=? AND name=?",
            ("singleuser", "default"),
        ) as cur:
            if await cur.fetchone() is not None:
                return

        async with db.execute(
            "SELECT project, yaml_text, applied_at FROM config WHERE id=1"
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return

        _project, yaml_text, applied_at = row

    from .storage_deploys import DeployRepository
    from .config.hashing import components_hash_from_rendered

    repo = DeployRepository(db_path)
    d = await repo.create("default", owner_user_id="singleuser")
    await repo.append_version(
        d["id"],
        yaml_text=yaml_text,
        components_hash=components_hash_from_rendered({}),
        applied_by_user_id="singleuser",
        result_json={"migrated_from_legacy_config": True, "applied_at": applied_at},
        kind="apply",
    )
