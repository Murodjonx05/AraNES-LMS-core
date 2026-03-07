import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.runtime import RuntimeContext, get_default_runtime

logger = logging.getLogger(__name__)


def run_startup_alembic_upgrade(*, runtime: RuntimeContext | None = None) -> None:
    runtime = runtime or get_default_runtime()
    command.upgrade(AlembicConfig(str(Path(runtime.config.BASE_DIR) / "alembic.ini")), "head")
    logger.info("Applied Alembic migrations on startup.")


def is_missing_schema_error(exc: OperationalError) -> bool:
    msg = str(exc).lower()
    return "no such table" in msg or "does not exist" in msg


def raise_missing_schema_help(exc: OperationalError) -> None:
    if not is_missing_schema_error(exc):
        raise exc
    raise RuntimeError(
        "Database schema is missing. Run `alembic upgrade head` "
        "or let the app retry startup with automatic Alembic migration."
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
    from src.user_role.bootstrap import seed_roles_if_missing

    runtime = runtime or get_default_runtime()
    session_factory = session_factory or runtime.session_factory

    async with session_factory() as session:
        await seed_roles_if_missing(session)
        ensure_translate_registrars_loaded()
        if (
            await seed_small_i18n_titles_if_missing(session, commit=False)
            or await seed_large_i18n_descriptions_if_missing(session, commit=False)
        ):
            await session.commit()
