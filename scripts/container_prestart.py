from __future__ import annotations

import asyncio
import logging

from src.runtime import get_default_runtime
from src.startup.bootstrap import (
    ensure_initial_super_user,
    run_bootstrap_seeding,
    run_startup_alembic_upgrade,
)


logger = logging.getLogger("aranes.prestart")


async def _run() -> None:
    runtime = get_default_runtime()
    try:
        run_startup_alembic_upgrade(runtime=runtime)
        await run_bootstrap_seeding(runtime=runtime)
        await ensure_initial_super_user(runtime=runtime)
        logger.info("Container prestart bootstrap completed.")
    finally:
        await runtime.engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    asyncio.run(_run())
