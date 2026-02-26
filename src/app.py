import authx.exceptions as authx_exceptions
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse

from src.api import all_routes
from src.auth.dependencies import require_access_token_payload
from src.runtime import RuntimeContext, get_default_runtime
from src.startup import lifespan


def create_app(runtime: RuntimeContext | None = None) -> FastAPI:
    runtime = runtime or get_default_runtime()
    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime

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
    runtime.security.handle_errors(app)

    @app.exception_handler(authx_exceptions.JWTDecodeError)
    async def _jwt_decode_error_handler(request, exc: authx_exceptions.JWTDecodeError):
        # AuthX defaults JWTDecodeError to 422; for protected endpoints we treat malformed
        # bearer tokens as authentication failures (401) for consistency with tests/clients.
        return JSONResponse(
            status_code=401,
            content={
                "message": str(exc) or "Invalid Token",
                "error_type": exc.__class__.__name__,
            },
        )

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
                    # Explicitly mark public routes as open to avoid inheriting security
                    # from any future global defaults.
                    operation["security"] = []

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)