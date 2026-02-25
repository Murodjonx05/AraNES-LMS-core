import logging
import sys

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Model, async_engine
from src.settings import APP

logger = logging.getLogger(__name__)


async def setup_schema() -> None:
    # Ensure all model modules are imported before metadata.create_all().
    import src.i18n.models  # noqa: F401
    import src.user_role.models  # noqa: F401

    async with async_engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)


async def run_compat_migrations_sqlite() -> None:
    async with async_engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(roles)")
        columns = {row[1] for row in result.fetchall()}
        if "title_key" in columns:
            return

        await conn.exec_driver_sql(
            "ALTER TABLE roles ADD COLUMN title_key VARCHAR(128) NOT NULL DEFAULT ''"
        )


def _can_prompt_superuser() -> bool:
    if not APP.BOOTSTRAP_SUPERUSER_PROMPT:
        return False
    return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())


async def ensure_initial_super_user() -> None:
    from src.utils.super_user import ensure_super_user_once

    if _can_prompt_superuser():
        await ensure_super_user_once()
        return

    logger.warning(
        "Skipping interactive superuser bootstrap (no TTY or BOOTSTRAP_SUPERUSER_PROMPT=false)."
    )


async def run_bootstrap_seeding() -> None:
    from src.i18n.bootstrap import (
        seed_large_i18n_descriptions_if_missing,
        seed_small_i18n_titles_if_missing,
    )
    from src.user_role.bootstrap import seed_roles_if_missing

    async with AsyncSession(bind=async_engine, expire_on_commit=False) as session:
        await seed_roles_if_missing(session)
        await seed_small_i18n_titles_if_missing(session)
        await seed_large_i18n_descriptions_if_missing(session)


async def lifespan(app: FastAPI):
    await setup_schema()
    await run_compat_migrations_sqlite()
    await ensure_initial_super_user()
    await run_bootstrap_seeding()
    yield
