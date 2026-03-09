from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import event, select


@pytest.mark.asyncio
async def test_startup_bootstrap_succeeds_with_enforced_foreign_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    integration_app: object,
    migrated_db_template: Path,
):
    db_path = tmp_path / "startup-bootstrap.sqlite3"
    shutil.copyfile(migrated_db_template, db_path)

    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_CREATE", "true")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_USERNAME", "superuser")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_PASSWORD", "superuser11")

    from src.runtime import build_runtime, reset_default_runtime
    from src.startup.bootstrap import ensure_initial_super_user, run_bootstrap_seeding
    from src.user_role.defaults import SUPERADMIN_ROLE_ID
    from src.user_role.models import Role, User

    base_config = getattr(getattr(integration_app, "state", None), "session_config", None)
    assert base_config is not None
    reset_default_runtime()
    runtime = build_runtime(
        replace(base_config, DATABASE_URL=f"sqlite+aiosqlite:///{db_path}")
    )

    @event.listens_for(runtime.engine.sync_engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection, connection_record):
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    try:
        await run_bootstrap_seeding(runtime=runtime)
        await ensure_initial_super_user(runtime=runtime)

        async with runtime.session_factory() as session:
            role_id = await session.scalar(select(Role.id).where(Role.id == SUPERADMIN_ROLE_ID).limit(1))
            superuser_role_id = await session.scalar(
                select(User.role_id).where(User.username == "superuser").limit(1)
            )

        assert role_id == SUPERADMIN_ROLE_ID
        assert superuser_role_id == SUPERADMIN_ROLE_ID
    finally:
        await runtime.engine.dispose()
        reset_default_runtime()
