from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from src.i18n import bootstrap as i18n_bootstrap
from src.i18n.models import TranslateDesc, TranslateTitle
from src.startup import bootstrap


class _DummySession:
    pass


class _DummySessionFactory:
    def __init__(self) -> None:
        self.session = _DummySession()

    def __call__(self):
        @asynccontextmanager
        async def _ctx():
            session = self.session

            @asynccontextmanager
            async def _begin():
                yield session

            session.begin = _begin  # type: ignore[attr-defined]
            yield session

        return _ctx()


def test_run_startup_alembic_upgrade_rejects_in_memory_sqlite():
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            BASE_DIR=Path("/tmp/app"),
        )
    )

    with patch("src.startup.bootstrap.command.upgrade") as upgrade_mock:
        with pytest.raises(RuntimeError, match="in-memory SQLite"):
            bootstrap.run_startup_alembic_upgrade(runtime=runtime)  # type: ignore[arg-type]

    upgrade_mock.assert_not_called()


@pytest.mark.parametrize(
    "exc",
    [
        OperationalError("SELECT 1", {}, Exception("no such table: users")),
        OperationalError("SELECT 1", {}, Exception("(1146, \"Table 'app.users' doesn't exist\")")),
        ProgrammingError("SELECT 1", {}, Exception('relation "users" does not exist')),
    ],
)
def test_is_missing_schema_error_supports_common_backend_messages(exc):
    assert bootstrap.is_missing_schema_error(exc) is True


def test_raise_missing_schema_help_clarifies_when_automatic_retry_applies():
    exc = OperationalError("SELECT 1", {}, Exception("no such table: users"))

    with pytest.raises(RuntimeError, match="Automatic startup migration is only attempted"):
        bootstrap.raise_missing_schema_help(exc)


@pytest.mark.asyncio
async def test_run_bootstrap_seeding_prefers_explicit_session_factory_over_default_runtime():
    session_factory = _DummySessionFactory()
    registered_small_translates = {"role.super_admin": {"en": "Super Admin"}}
    registered_large_translates = {("role", "super_admin"): {"en": "Super Admin role"}}

    with (
        patch("src.startup.bootstrap.get_default_runtime", side_effect=AssertionError("default runtime used")),
        patch("src.user_role.bootstrap.seed_roles_if_missing", new=AsyncMock()) as role_seed_mock,
        patch("src.i18n.bootstrap.ensure_translate_registrars_loaded") as registrars_mock,
        patch(
            "src.i18n.translates.get_registered_small_translates",
            return_value=registered_small_translates,
        ) as small_registry_mock,
        patch(
            "src.i18n.translates.get_registered_large_translates",
            return_value=registered_large_translates,
        ) as large_registry_mock,
        patch("src.i18n.bootstrap.seed_small_i18n_titles_if_missing", new=AsyncMock()) as small_seed_mock,
        patch("src.i18n.bootstrap.seed_large_i18n_descriptions_if_missing", new=AsyncMock()) as large_seed_mock,
    ):
        await bootstrap.run_bootstrap_seeding(session_factory=session_factory)

    role_seed_mock.assert_awaited_once_with(session_factory.session, commit=False)
    registrars_mock.assert_called_once_with()
    small_registry_mock.assert_called_once_with()
    large_registry_mock.assert_called_once_with()
    small_seed_mock.assert_awaited_once_with(
        session_factory.session,
        commit=False,
        registered_translates=registered_small_translates,
    )
    large_seed_mock.assert_awaited_once_with(
        session_factory.session,
        commit=False,
        registered_translates=registered_large_translates,
    )


@pytest.mark.asyncio
async def test_seed_small_i18n_titles_if_missing_uses_preloaded_translates_without_registry_reload():
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: []),
            )
        ),
        add_all=Mock(),
    )
    registered_translates = {"role.super_admin": {"en": "Super Admin"}}

    with (
        patch(
            "src.i18n.bootstrap.ensure_translate_registrars_loaded",
            side_effect=AssertionError("registrars should not be loaded"),
        ),
        patch(
            "src.i18n.bootstrap.get_registered_small_translates",
            side_effect=AssertionError("registry snapshot should not be reloaded"),
        ),
    ):
        created = await i18n_bootstrap.seed_small_i18n_titles_if_missing(
            session,  # type: ignore[arg-type]
            commit=False,
            registered_translates=registered_translates,
        )

    assert created == 1
    session.add_all.assert_called_once()
    added_items = session.add_all.call_args.args[0]
    assert len(added_items) == 1
    assert isinstance(added_items[0], TranslateTitle)
    assert added_items[0].key == "role.super_admin"
    assert added_items[0].title == {"en": "Super Admin"}


@pytest.mark.asyncio
async def test_seed_large_i18n_descriptions_if_missing_uses_preloaded_translates_without_registry_reload():
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
        add_all=Mock(),
    )
    registered_translates = {("role", "super_admin"): {"en": "Super Admin role"}}

    with (
        patch(
            "src.i18n.bootstrap.ensure_translate_registrars_loaded",
            side_effect=AssertionError("registrars should not be loaded"),
        ),
        patch(
            "src.i18n.bootstrap.get_registered_large_translates",
            side_effect=AssertionError("registry snapshot should not be reloaded"),
        ),
    ):
        created = await i18n_bootstrap.seed_large_i18n_descriptions_if_missing(
            session,  # type: ignore[arg-type]
            commit=False,
            registered_translates=registered_translates,
        )

    assert created == 1
    session.add_all.assert_called_once()
    added_items = session.add_all.call_args.args[0]
    assert len(added_items) == 1
    assert isinstance(added_items[0], TranslateDesc)
    assert added_items[0].key1 == "role"
    assert added_items[0].key2 == "super_admin"
    assert added_items[0].description == {"en": "Super Admin role"}
