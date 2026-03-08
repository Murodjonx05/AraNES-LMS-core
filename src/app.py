import authx.exceptions as authx_exceptions
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text

from src.api import all_routes
from src.auth.dependencies import require_access_token_payload
from src.runtime import RuntimeContext, get_default_runtime
from src.startup import lifespan
from src.utils.inprocess_http import attach_inprocess_http
from src.utils.profiler import emit_request_profile
from src.utils.rate_limit import InMemoryRateLimiter, RedisRateLimiter

_REQUEST_LOGGER = logging.getLogger("aranes.request")
_AUDIT_LOGGER = logging.getLogger("aranes.audit")
_RATE_LIMITED_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/reset",
    }
)
_AUDITED_PREFIXES = ("/api/v1/rbac", "/api/v1/i18n")
_AUDITED_EXACT_PATHS = frozenset({"/api/v1/auth/reset"})
_OPERABILITY_LOGGER = logging.getLogger("aranes.operability")
_PROFILER_LOGGER = logging.getLogger("aranes.profiler")
_SECURITY_LOGGER = logging.getLogger("aranes.security")


def _extract_actor_subject(request, runtime: RuntimeContext) -> str | None:
    cached = getattr(request.state, "actor_subject", None)
    if cached is not None:
        return cached
    if getattr(request.state, "actor_subject_resolved", False):
        return None

    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        request.state.actor_subject_resolved = True
        return None
    token = auth_header[7:].strip()
    if not token:
        request.state.actor_subject_resolved = True
        return None
    try:
        payload = runtime.security._decode_token(token)
    except Exception as exc:
        request.state.actor_subject_resolved = True
        _SECURITY_LOGGER.warning(
            "actor subject extraction failed",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "error_type": exc.__class__.__name__,
            },
        )
        return None
    request.state.actor_subject = getattr(payload, "sub", None)
    request.state.actor_subject_resolved = True
    return request.state.actor_subject


def _should_audit_request(path: str, method: str) -> bool:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return False
    return path in _AUDITED_EXACT_PATHS or path.startswith(_AUDITED_PREFIXES)


def _client_host(request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return str(request.client.host)


def _emit_structured_log(logger: logging.Logger, event: str, **payload: object) -> None:
    logger.info(json.dumps({"event": event, **payload}, ensure_ascii=True, sort_keys=True))


def _safe_emit_request_profile(
    *,
    method: str,
    path: str,
    status_code: int,
    elapsed_ms: float,
    request_id: str,
) -> None:
    try:
        emit_request_profile(
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
    except Exception:
        _PROFILER_LOGGER.exception(
            "request profiler emit failed",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": status_code,
            },
        )


def _apply_request_id(response: JSONResponse, request_id: str):
    response.headers["X-Request-ID"] = request_id
    return response


def _record_request_observation(
    *,
    request,
    runtime: RuntimeContext,
    method: str,
    path: str,
    status_code: int,
    elapsed_ms: float,
    request_id: str,
    client_host: str,
) -> None:
    actor_subject = _extract_actor_subject(request, runtime)
    _safe_emit_request_profile(
        method=method,
        path=path,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        request_id=request_id,
    )
    if runtime.config.REQUEST_LOG_ENABLED:
        _emit_structured_log(
            _REQUEST_LOGGER,
            "request",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=round(elapsed_ms, 3),
            client_host=client_host,
            actor=actor_subject,
        )
    if runtime.config.AUDIT_LOG_ENABLED and _should_audit_request(path, method):
        _emit_structured_log(
            _AUDIT_LOGGER,
            "audit",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            client_host=client_host,
            actor=actor_subject,
        )


def _build_internal_server_error_response(request: Request, exc: Exception):
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("x-request-id")
        or uuid4().hex
    )
    _OPERABILITY_LOGGER.exception(
        "unhandled request exception",
        extra={"request_id": request_id, "path": request.url.path},
        exc_info=exc,
    )
    return _apply_request_id(
        JSONResponse(
            status_code=500,
            content={
                "detail": "Internal Server Error",
                "request_id": request_id,
            },
        ),
        request_id,
    )


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


def create_app(runtime: RuntimeContext | None = None) -> FastAPI:
    runtime = runtime or get_default_runtime()
    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime
    app.state.rate_limiter = InMemoryRateLimiter()
    app.state.redis_rate_limiter = RedisRateLimiter(runtime.cache_service)

    def _current_runtime() -> RuntimeContext:
        return getattr(app.state, "runtime", None) or runtime

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
            _OPERABILITY_LOGGER.exception(
                "database readiness check failed",
                extra={"request_id": request_id},
                exc_info=exc,
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
            "database_backend": active_runtime.engine.url.get_backend_name(),
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
        status_code = 500
        client_host = _client_host(request)

        is_rate_limited = False
        if active_runtime.config.RATE_LIMIT_ENABLED and path in _RATE_LIMITED_PATHS:
            rate_limit_key = f"{client_host}:{path}"
            if active_runtime.cache_service.enabled:
                redis_allowed = await app.state.redis_rate_limiter.allow(
                    rate_limit_key,
                    limit=active_runtime.config.RATE_LIMIT_MAX_REQUESTS,
                    window_seconds=active_runtime.config.RATE_LIMIT_WINDOW_SECONDS,
                )
                if redis_allowed is None:
                    _OPERABILITY_LOGGER.warning(
                        "rate limiter degraded; denying request",
                        extra={
                            "request_id": request_id,
                            "path": path,
                            "client_host": client_host,
                        },
                    )
                    is_rate_limited = True
                else:
                    is_rate_limited = not redis_allowed
            else:
                is_rate_limited = not app.state.rate_limiter.allow(
                    rate_limit_key,
                    limit=active_runtime.config.RATE_LIMIT_MAX_REQUESTS,
                    window_seconds=active_runtime.config.RATE_LIMIT_WINDOW_SECONDS,
                )

        if is_rate_limited:
            response = _apply_request_id(
                JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                ),
                request_id,
            )
            status_code = response.status_code
        else:
            try:
                response = await call_next(request)
            except Exception as exc:
                response = _build_internal_server_error_response(request, exc)
            status_code = response.status_code
            _apply_request_id(response, request_id)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        _record_request_observation(
            request=request,
            runtime=active_runtime,
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            request_id=request_id,
            client_host=client_host,
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

    app.include_router(all_routes)
    attach_inprocess_http(app)
    runtime.security.handle_errors(app)

    @app.exception_handler(authx_exceptions.JWTDecodeError)
    async def _jwt_decode_error_handler(request, exc: authx_exceptions.JWTDecodeError):
        request_id = (
            getattr(request.state, "request_id", None)
            or request.headers.get("x-request-id")
            or uuid4().hex
        )
        return _apply_request_id(
            JSONResponse(
                status_code=401,
                content={
                    "message": str(exc) or "Invalid Token",
                    "error_type": exc.__class__.__name__,
                },
            ),
            request_id,
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        return _build_internal_server_error_response(request, exc)

    def _is_route_protected(route: APIRoute) -> bool:
        dependency_calls = [dep.call for dep in route.dependant.dependencies]
        return require_access_token_payload in dependency_calls

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        components = openapi_schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }

        paths = openapi_schema.get("paths", {})
        protected_operations: set[tuple[str, str]] = set()
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            if not _is_route_protected(route):
                continue
            for method in route.methods or set():
                protected_operations.add((route.path, method.lower()))

        for path, operations in paths.items():
            for method, operation in operations.items():
                if (path, method.lower()) in protected_operations:
                    operation["security"] = [{"BearerAuth": []}]
                else:
                    operation["security"] = []

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
