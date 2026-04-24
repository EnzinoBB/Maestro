import os
import tempfile
import pytest
import aiosqlite

from app.storage import Storage
from app.storage_deploys import DeployRepository


_LEGACY_YAML = """api_version: maestro/v1
project: legacy-app
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  c1:
    source: {type: docker, image: nginx}
    run: {type: docker}
deployment:
  - host: h1
    components: [c1]
"""


@pytest.mark.asyncio
async def test_init_migrates_legacy_config_into_default_deploy():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")

        s = Storage(path)
        await s.init()
        await s.save_config("legacy-app", _LEGACY_YAML)

        # Drop new-schema rows to simulate an upgrade-in-place
        async with aiosqlite.connect(path) as db:
            await db.execute("DELETE FROM deploy_versions;")
            await db.execute("DELETE FROM deploys;")
            await db.commit()

        # Re-run init: migration must recreate default deploy
        await Storage(path).init()

        repo = DeployRepository(path)
        default = await repo.get_by_name("singleuser", "default")
        assert default is not None
        assert default["owner_user_id"] == "singleuser"
        assert default["current_version"] == 1

        versions = await repo.list_versions(default["id"])
        assert len(versions) == 1
        assert versions[0]["yaml_text"] == _LEGACY_YAML
        assert versions[0]["kind"] == "apply"


@pytest.mark.asyncio
async def test_init_is_idempotent_no_double_migration():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        s = Storage(path)
        await s.init()
        await s.save_config("legacy-app", _LEGACY_YAML)
        await Storage(path).init()  # migrates
        await Storage(path).init()  # must not create a second version

        repo = DeployRepository(path)
        default = await repo.get_by_name("singleuser", "default")
        assert default is not None
        versions = await repo.list_versions(default["id"])
        assert len(versions) == 1


@pytest.mark.asyncio
async def test_init_no_legacy_config_does_not_create_default():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)
        default = await repo.get_by_name("singleuser", "default")
        assert default is None
