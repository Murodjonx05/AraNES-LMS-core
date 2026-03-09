from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import ProgrammingError

from scripts import container_prestart


def _build_runtime():
    return SimpleNamespace(
        cache_service=SimpleNamespace(close=AsyncMock()),
        engine=SimpleNamespace(dispose=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_container_prestart_translates_missing_schema_errors_after_migration():
    runtime = _build_runtime()
    missing_schema_exc = ProgrammingError("SELECT ...", {}, Exception('relation "roles" does not exist'))
    translated_error = RuntimeError("missing schema help")

    with (
        patch("scripts.container_prestart.get_default_runtime", return_value=runtime),
        patch("scripts.container_prestart.run_startup_alembic_upgrade") as alembic_mock,
        patch(
            "scripts.container_prestart.run_bootstrap_seeding",
            new=AsyncMock(side_effect=missing_schema_exc),
        ) as seed_mock,
        patch("scripts.container_prestart.ensure_initial_super_user", new=AsyncMock()) as superuser_mock,
        patch(
            "scripts.container_prestart.raise_missing_schema_help",
            new=Mock(side_effect=translated_error),
        ) as help_mock,
    ):
        with pytest.raises(RuntimeError, match="missing schema help"):
            await container_prestart._run()

    alembic_mock.assert_called_once_with(runtime=runtime)
    seed_mock.assert_awaited_once_with(runtime=runtime)
    superuser_mock.assert_not_awaited()
    help_mock.assert_called_once_with(missing_schema_exc)
    runtime.cache_service.close.assert_awaited_once()
    runtime.engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_container_prestart_closes_cache_and_engine_on_success():
    runtime = _build_runtime()

    with (
        patch("scripts.container_prestart.get_default_runtime", return_value=runtime),
        patch("scripts.container_prestart.run_startup_alembic_upgrade") as alembic_mock,
        patch("scripts.container_prestart.run_bootstrap_seeding", new=AsyncMock()) as seed_mock,
        patch("scripts.container_prestart.ensure_initial_super_user", new=AsyncMock()) as superuser_mock,
    ):
        await container_prestart._run()

    alembic_mock.assert_called_once_with(runtime=runtime)
    seed_mock.assert_awaited_once_with(runtime=runtime)
    superuser_mock.assert_awaited_once_with(runtime=runtime)
    runtime.cache_service.close.assert_awaited_once()
    runtime.engine.dispose.assert_awaited_once()
