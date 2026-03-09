from __future__ import annotations

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from src.auth.dependencies import require_access_token_payload


def _dependant_requires_access_token(dependant: Dependant) -> bool:
    for dependency in dependant.dependencies:
        if dependency.call is require_access_token_payload:
            return True
        if _dependant_requires_access_token(dependency):
            return True
    return False


def _is_route_protected(route: APIRoute) -> bool:
    return _dependant_requires_access_token(route.dependant)


def install_bearer_openapi(app: FastAPI) -> None:
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

        protected_operations: set[tuple[str, str]] = set()
        for route in app.routes:
            if not isinstance(route, APIRoute) or not _is_route_protected(route):
                continue
            for method in route.methods or set():
                protected_operations.add((route.path, method.lower()))

        for path, operations in openapi_schema.get("paths", {}).items():
            for method, operation in operations.items():
                operation["security"] = (
                    [{"BearerAuth": []}] if (path, method.lower()) in protected_operations else []
                )

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
