import logging

from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from src.startup.bootstrap import (
    ensure_initial_super_user,
    is_missing_schema_error,
    raise_missing_schema_help,
    run_bootstrap_seeding,
    run_startup_alembic_upgrade,
)
from src.utils.inprocess_http import close_inprocess_http

logger = logging.getLogger(__name__)


async def lifespan(app: FastAPI):
    runtime = getattr(app.state, "runtime", None)
    try:
        if runtime is not None:
            if runtime.cache_service.enabled and not await runtime.cache_service.ping():
                logger.warning(
                    "Redis is unavailable during startup; continuing with degraded cache mode."
                )
            await runtime.cache_service.start_heartbeat()
        startup_db_bootstrap_enabled = bool(
            getattr(getattr(runtime, "config", None), "STARTUP_DB_BOOTSTRAP_ENABLED", True)
        )
        if startup_db_bootstrap_enabled:
            try:
                await run_bootstrap_seeding(runtime=runtime)
                await ensure_initial_super_user(runtime=runtime)
            except OperationalError as exc:
                if not is_missing_schema_error(exc):
                    raise
                run_startup_alembic_upgrade(runtime=runtime)
                try:
                    await run_bootstrap_seeding(runtime=runtime)
                    await ensure_initial_super_user(runtime=runtime)
                except OperationalError as retry_exc:
                    raise_missing_schema_help(retry_exc)
        yield
    finally:
        if runtime is not None:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
        await close_inprocess_http(app)
