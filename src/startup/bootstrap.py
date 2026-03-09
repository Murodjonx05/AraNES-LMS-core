import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import is_in_memory_sqlite_url
from src.runtime import RuntimeContext, get_default_runtime

logger = logging.getLogger(__name__)
_MISSING_SCHEMA_MARKERS = (
    "no such table",
    "does not exist",
    "doesn't exist",
    "base table or view not found",
    "undefined table",
)


def run_startup_alembic_upgrade(*, runtime: RuntimeContext | None = None) -> None:
    runtime = runtime or get_default_runtime()
    if is_in_memory_sqlite_url(runtime.config.DATABASE_URL):
        raise RuntimeError(
            "Automatic startup Alembic migration is not supported for in-memory SQLite databases. "
            "Use a file-backed database or initialize schema on the runtime engine before startup."
        )
    command.upgrade(AlembicConfig(str(Path(runtime.config.BASE_DIR) / "alembic.ini")), "head")
    logger.info("Applied Alembic migrations on startup.")


def is_missing_schema_error(exc: DBAPIError) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _MISSING_SCHEMA_MARKERS)


def raise_missing_schema_help(exc: DBAPIError) -> None:
    if not is_missing_schema_error(exc):
        raise exc
    raise RuntimeError(
        "Database schema is missing or incomplete. Run `alembic upgrade head`. "
        "Automatic startup migration is only attempted when DB bootstrap is enabled "
        "and the backend reports a missing-schema error."
    ) from exc


async def ensure_initial_super_user(*, runtime: RuntimeContext | None = None) -> None:
    from src.utils.super_user import ensure_super_user_from_env_if_enabled

    runtime = runtime or get_default_runtime()
    created = await ensure_super_user_from_env_if_enabled(session_factory=runtime.session_factory)
    if created:
        logger.info("Superuser bootstrap completed from environment configuration.")


async def run_bootstrap_seeding(
    *,
    runtime: RuntimeContext | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    from src.i18n.bootstrap import (
        ensure_translate_registrars_loaded,
        seed_large_i18n_descriptions_if_missing,
        seed_small_i18n_titles_if_missing,
    )
    from src.i18n.translates import get_registered_large_translates, get_registered_small_translates
    from src.user_role.bootstrap import seed_roles_if_missing

    if session_factory is None:
        runtime = runtime or get_default_runtime()
        session_factory = runtime.session_factory

    async with session_factory() as session:
        async with session.begin():
            await seed_roles_if_missing(session, commit=False)
            ensure_translate_registrars_loaded()
            registered_small_translates = get_registered_small_translates()
            registered_large_translates = get_registered_large_translates()
            await seed_small_i18n_titles_if_missing(
                session,
                commit=False,
                registered_translates=registered_small_translates,
            )
            await seed_large_i18n_descriptions_if_missing(
                session,
                commit=False,
                registered_translates=registered_large_translates,
            )
