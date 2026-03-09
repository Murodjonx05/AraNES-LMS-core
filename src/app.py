import authx.exceptions as authx_exceptions
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from src.api import all_routes
from src.http.errors import build_internal_server_error_response, build_jwt_decode_error_response
from src.http.observability import (
    OPERABILITY_LOGGER,
    apply_request_id,
    client_host,
    record_request_observation,
)
from src.http.openapi import install_bearer_openapi
from src.runtime import RuntimeContext, get_default_runtime
from src.startup import lifespan
from src.utils.inprocess_http import attach_inprocess_http
from src.utils.structured_logging import setup_logging


async def _build_redis_health(runtime: RuntimeContext) -> dict[str, object]:
    cache_service = runtime.cache_service
    if not getattr(cache_service, "enabled", False):
        return {"enabled": False, "status": "disabled"}
    ok = await cache_service.ping()
    return {
        "enabled": True,
        "status": "ok" if ok else "unavailable",
        "available": ok,
    }


def _has_operability_runtime_contract(runtime: object | None) -> bool:
    if runtime is None:
        return False
    config = getattr(runtime, "config", None)
    cache_service = getattr(runtime, "cache_service", None)
    engine = getattr(runtime, "engine", None)
    return (
        config is not None
        and cache_service is not None
        and hasattr(engine, "connect")
    )


def _resolve_app_runtime(app: FastAPI, fallback_runtime: RuntimeContext) -> RuntimeContext:
    app_runtime = getattr(getattr(app, "state", None), "runtime", None)
    if _has_operability_runtime_contract(app_runtime):
        return app_runtime
    return fallback_runtime


def _engine_backend_name(engine: object) -> str:
    engine_url = getattr(engine, "url", None)
    get_backend_name = getattr(engine_url, "get_backend_name", None)
    if callable(get_backend_name):
        return str(get_backend_name())
    return "unknown"


def create_app(runtime: RuntimeContext | None = None) -> FastAPI:
    runtime = runtime or get_default_runtime()
    setup_logging(runtime.config)
    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime
    app.state.metrics_registry = CollectorRegistry()

    def _current_runtime() -> RuntimeContext:
        return _resolve_app_runtime(app, runtime)

    @app.get("/health", tags=["system"])
    async def health():
        redis = await _build_redis_health(_current_runtime())
        status = "ok" if redis["status"] in {"ok", "disabled"} else "degraded"
        return {"status": status, "service": "aranes-lms-core", "redis": redis}

    @app.get("/ready", tags=["system"])
    async def ready(request: Request):
        active_runtime = _current_runtime()
        redis = await _build_redis_health(active_runtime)
        try:
            async with active_runtime.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            request_id = (
                getattr(request.state, "request_id", None)
                or request.headers.get("x-request-id")
                or uuid4().hex
            )
            OPERABILITY_LOGGER.exception(
                "database readiness check failed",
                request_id=request_id,
                error_type=exc.__class__.__name__,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "database": "error",
                    "redis": redis,
                    "detail": "Database is unavailable.",
                },
            )
        return {
            "status": "ready",
            "database": "ok",
            "database_backend": _engine_backend_name(active_runtime.engine),
            "redis": redis,
        }

    @app.middleware("http")
    async def _observe_requests(request, call_next):
        active_runtime = _current_runtime()
        method = request.method
        path = request.url.path
        request_id = request.headers.get("x-request-id") or uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        client_host_value = client_host(request)

        try:
            response = await call_next(request)
        except Exception as exc:
            response = build_internal_server_error_response(request, exc)
        status_code = response.status_code
        apply_request_id(response, request_id)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        record_request_observation(
            request=request,
            runtime=active_runtime,
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            request_id=request_id,
            client_host_value=client_host_value,
        )
        return response

    trusted_origins = runtime.config.CORS.get("ALLOW_ORIGINS") or []
    if "*" in trusted_origins:
        raise RuntimeError("Wildcard CORS origins are not allowed.")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=trusted_origins,
        allow_credentials=bool(runtime.config.CORS.get("ALLOW_CREDENTIALS")),
        allow_methods=runtime.config.CORS.get("ALLOW_METHODS"),
        allow_headers=runtime.config.CORS.get("ALLOW_HEADERS"),
    )
    Instrumentator(
        excluded_handlers=["/metrics"],
        registry=app.state.metrics_registry,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False, tags=["system"])

    app.include_router(all_routes)
    attach_inprocess_http(app)
    runtime.security.handle_errors(app)

    @app.exception_handler(authx_exceptions.JWTDecodeError)
    async def _jwt_decode_error_handler(request, exc: authx_exceptions.JWTDecodeError):
        return build_jwt_decode_error_response(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        return build_internal_server_error_response(request, exc)

    install_bearer_openapi(app)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    runtime = getattr(app.state, "runtime", None) or get_default_runtime()
    uvicorn.run(app, host=runtime.config.HOST, port=runtime.config.PORT)
