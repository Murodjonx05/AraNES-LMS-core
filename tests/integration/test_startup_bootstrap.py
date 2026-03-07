from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import event, select


@pytest.mark.asyncio
async def test_startup_bootstrap_succeeds_with_enforced_foreign_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    migrated_db_template: Path,
):
    db_path = tmp_path / "startup-bootstrap.sqlite3"
    shutil.copy2(migrated_db_template, db_path)

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "false")
    monkeypatch.setenv("PBKDF2_ITERATIONS", "1")
    monkeypatch.setenv("APP_PROFILING_ENABLED", "false")
    monkeypatch.setenv("APP_FUNCTION_PROFILING_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_CREATE", "true")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_USERNAME", "superuser")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_PASSWORD", "superuser11")

    from src.app import create_app
    from src.config import build_app_config
    from src.runtime import build_runtime, reset_default_runtime
    from src.user_role.defaults import SUPERADMIN_ROLE_ID
    from src.user_role.models import Role, User

    reset_default_runtime()
    runtime = build_runtime(build_app_config())

    @event.listens_for(runtime.engine.sync_engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection, connection_record):
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    app = create_app(runtime)
    try:
        async with app.router.lifespan_context(app):
            pass

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
