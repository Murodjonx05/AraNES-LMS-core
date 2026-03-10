import logging

import httpx
from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from src.startup.bootstrap import (
    ensure_initial_super_user,
    is_missing_schema_error,
    raise_missing_schema_help,
    run_bootstrap_seeding,
    run_startup_alembic_upgrade,
)
from src.utils.cache import resolve_heartbeat_delay
from src.utils.inprocess_http import close_inprocess_http

logger = logging.getLogger(__name__)


async def _fetch_gateway_openapi(gateway_url: str) -> dict | None:
    base = gateway_url.rstrip("/")
    url = f"{base}/openapi.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch gateway OpenAPI from %s: %s", url, exc)
    return None


async def lifespan(app: FastAPI):
    runtime = getattr(app.state, "runtime", None)
    try:
        if runtime is not None:
            heartbeat_initial_delay = 0
            if runtime.cache_service.enabled and not await runtime.cache_service.ping():
                logger.warning(
                    "Redis is unavailable during startup; continuing with degraded cache mode."
                )
                heartbeat_initial_delay = resolve_heartbeat_delay(
                    tuple(getattr(runtime.cache_service, "heartbeat_schedule_seconds", ()) or ()),
                    1,
                )
            elif runtime.cache_service.enabled:
                heartbeat_initial_delay = resolve_heartbeat_delay(
                    tuple(getattr(runtime.cache_service, "heartbeat_schedule_seconds", ()) or ()),
                    0,
                )
            await runtime.cache_service.start_heartbeat_with_delay(
                initial_delay_seconds=heartbeat_initial_delay
            )
        startup_db_bootstrap_enabled = bool(
            getattr(getattr(runtime, "config", None), "STARTUP_DB_BOOTSTRAP_ENABLED", True)
        )
        if startup_db_bootstrap_enabled:
            try:
                await run_bootstrap_seeding(runtime=runtime)
                await ensure_initial_super_user(runtime=runtime)
            except DBAPIError as exc:
                if not is_missing_schema_error(exc):
                    raise
                run_startup_alembic_upgrade(runtime=runtime)
                try:
                    await run_bootstrap_seeding(runtime=runtime)
                    await ensure_initial_super_user(runtime=runtime)
                except DBAPIError as retry_exc:
                    raise_missing_schema_help(retry_exc)
        else:
            try:
                await ensure_initial_super_user(runtime=runtime)
            except DBAPIError as exc:
                raise_missing_schema_help(exc)

        if runtime is not None:
            gateway_url = getattr(runtime.config, "PLUGIN_GATEWAY_URL", None)
            if gateway_url:
                app.state.gateway_openapi_schema = await _fetch_gateway_openapi(gateway_url)
                app.state.plugin_gateway_client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
            else:
                app.state.gateway_openapi_schema = None
                app.state.plugin_gateway_client = None
        else:
            app.state.gateway_openapi_schema = None
            app.state.plugin_gateway_client = None

        yield
    finally:
        if runtime is not None:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
        client = getattr(getattr(app, "state", None), "plugin_gateway_client", None)
        if client is not None:
            await client.aclose()
        await close_inprocess_http(app)
