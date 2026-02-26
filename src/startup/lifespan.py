from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from src.startup.bootstrap import (
    ensure_initial_super_user,
    is_missing_schema_error,
    raise_missing_schema_help,
    run_bootstrap_seeding,
    run_startup_alembic_upgrade,
)


async def lifespan(app: FastAPI):
    runtime = getattr(app.state, "runtime", None)
    try:
        # Keep superuser bootstrap non-interactive inside app startup.
        await ensure_initial_super_user(runtime=runtime)
        await run_bootstrap_seeding(runtime=runtime)
    except OperationalError as exc:
        if not is_missing_schema_error(exc):
            raise
        run_startup_alembic_upgrade(runtime=runtime)
        try:
            await ensure_initial_super_user(runtime=runtime)
            await run_bootstrap_seeding(runtime=runtime)
        except OperationalError as retry_exc:
            raise_missing_schema_help(retry_exc)
    yield
