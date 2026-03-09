from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError, ProgrammingError

from src.startup.lifespan import lifespan


def _build_runtime(*, startup_db_bootstrap_enabled: bool = True):
    return SimpleNamespace(
        config=SimpleNamespace(STARTUP_DB_BOOTSTRAP_ENABLED=startup_db_bootstrap_enabled),
        cache_service=SimpleNamespace(
            enabled=False,
            heartbeat_schedule_seconds=(60,),
            ping=AsyncMock(return_value=False),
            start_heartbeat_with_delay=AsyncMock(),
            close=AsyncMock(),
        ),
        engine=SimpleNamespace(dispose=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_lifespan_still_runs_superuser_bootstrap_when_db_bootstrap_disabled():
    app = FastAPI(lifespan=lifespan)
    runtime = _build_runtime(startup_db_bootstrap_enabled=False)
    app.state.runtime = runtime

    with (
        patch("src.startup.lifespan.run_bootstrap_seeding", new=AsyncMock()) as seed_mock,
        patch("src.startup.lifespan.ensure_initial_super_user", new=AsyncMock()) as superuser_mock,
    ):
        async with app.router.lifespan_context(app):
            pass

    seed_mock.assert_not_awaited()
    superuser_mock.assert_awaited_once_with(runtime=runtime)
    runtime.cache_service.start_heartbeat_with_delay.assert_awaited_once_with(
        initial_delay_seconds=0
    )
    runtime.cache_service.close.assert_awaited_once()
    runtime.engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_raises_missing_schema_help_when_superuser_bootstrap_hits_missing_schema():
    app = FastAPI(lifespan=lifespan)
    runtime = _build_runtime(startup_db_bootstrap_enabled=False)
    app.state.runtime = runtime
    missing_schema_exc = OperationalError("SELECT ...", {}, Exception("no such table: roles"))
    translated_error = RuntimeError("missing schema help")

    with (
        patch("src.startup.lifespan.run_bootstrap_seeding", new=AsyncMock()) as seed_mock,
        patch(
            "src.startup.lifespan.ensure_initial_super_user",
            new=AsyncMock(side_effect=missing_schema_exc),
        ) as superuser_mock,
        patch("src.startup.lifespan.raise_missing_schema_help", new=Mock(side_effect=translated_error)) as help_mock,
    ):
        with pytest.raises(RuntimeError, match="missing schema help"):
            async with app.router.lifespan_context(app):
                pass

    seed_mock.assert_not_awaited()
    superuser_mock.assert_awaited_once_with(runtime=runtime)
    help_mock.assert_called_once_with(missing_schema_exc)
    runtime.cache_service.close.assert_awaited_once()
    runtime.engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_retries_startup_migration_on_programming_error_missing_schema():
    app = FastAPI(lifespan=lifespan)
    runtime = _build_runtime(startup_db_bootstrap_enabled=True)
    app.state.runtime = runtime
    missing_schema_exc = ProgrammingError("SELECT ...", {}, Exception('relation "roles" does not exist'))

    with (
        patch(
            "src.startup.lifespan.run_bootstrap_seeding",
            new=AsyncMock(side_effect=[missing_schema_exc, None]),
        ) as seed_mock,
        patch("src.startup.lifespan.ensure_initial_super_user", new=AsyncMock()) as superuser_mock,
        patch("src.startup.lifespan.run_startup_alembic_upgrade") as alembic_mock,
    ):
        async with app.router.lifespan_context(app):
            pass

    assert seed_mock.await_count == 2
    alembic_mock.assert_called_once_with(runtime=runtime)
    superuser_mock.assert_awaited_once_with(runtime=runtime)
    runtime.cache_service.close.assert_awaited_once()
    runtime.engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_delays_first_redis_heartbeat_after_failed_startup_ping():
    app = FastAPI(lifespan=lifespan)
    runtime = _build_runtime(startup_db_bootstrap_enabled=False)
    runtime.cache_service.enabled = True
    runtime.cache_service.heartbeat_schedule_seconds = (30, 300)
    runtime.cache_service.ping = AsyncMock(return_value=False)
    app.state.runtime = runtime

    with patch("src.startup.lifespan.ensure_initial_super_user", new=AsyncMock()):
        async with app.router.lifespan_context(app):
            pass

    runtime.cache_service.start_heartbeat_with_delay.assert_awaited_once_with(
        initial_delay_seconds=30
    )
