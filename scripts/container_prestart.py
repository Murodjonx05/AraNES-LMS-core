from __future__ import annotations

import asyncio
import logging

from sqlalchemy.exc import DBAPIError

from src.runtime import get_default_runtime
from src.startup.bootstrap import (
    ensure_initial_super_user,
    raise_missing_schema_help,
    run_bootstrap_seeding,
    run_startup_alembic_upgrade,
)


logger = logging.getLogger("aranes.prestart")


async def _run() -> None:
    runtime = get_default_runtime()
    try:
        run_startup_alembic_upgrade(runtime=runtime)
        try:
            await run_bootstrap_seeding(runtime=runtime)
            await ensure_initial_super_user(runtime=runtime)
        except DBAPIError as exc:
            raise_missing_schema_help(exc)
        logger.info("Container prestart bootstrap completed.")
    finally:
        await runtime.cache_service.close()
        await runtime.engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    asyncio.run(_run())
