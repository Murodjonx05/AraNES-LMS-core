from __future__ import annotations

import copy
import logging

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from src.auth.dependencies import require_access_token_payload

logger = logging.getLogger(__name__)


def _dependant_requires_access_token(dependant: Dependant) -> bool:
    for dependency in dependant.dependencies:
        if dependency.call is require_access_token_payload:
            return True
        if _dependant_requires_access_token(dependency):
            return True
    return False


def _dependency_calls_recursive(dependant) -> set:
    """Collect all dependency callables in the dependency tree (including nested)."""
    out = set()
    for dep in getattr(dependant, "dependencies", []):
        if dep.call is not None:
            out.add(dep.call)
        out |= _dependency_calls_recursive(dep)
    return out


def _is_route_protected(route: APIRoute) -> bool:
    return require_access_token_payload in _dependency_calls_recursive(route.dependant)


def _merge_gateway_openapi(core_schema: dict, gateway_schema: dict) -> None:
    gateway_paths = gateway_schema.get("paths", {})
    for path_name, path_item in gateway_paths.items():
        if path_name in core_schema.setdefault("paths", {}):
            logger.warning("Gateway path %s overwrites core path", path_name)
        item = copy.deepcopy(path_item)
        path_prefix = path_name.strip("/").replace("/", "_").replace("-", "_") or "gateway"
        for method, operation in item.items():
            if method in ("get", "post", "put", "patch", "delete", "head", "options") and isinstance(operation, dict):
                operation["security"] = [{"BearerAuth": []}]
                operation["operationId"] = f"{path_prefix}_{method}"
        core_schema["paths"][path_name] = item

    gateway_schemas = gateway_schema.get("components", {}).get("schemas", {})
    core_components = core_schema.setdefault("components", {})
    core_schemas = core_components.setdefault("schemas", {})
    for schema_name, schema_val in gateway_schemas.items():
        if schema_name in core_schemas:
            logger.warning("Gateway schema %s overwrites core schema", schema_name)
        core_schemas[schema_name] = schema_val

    gateway_tags = gateway_schema.get("tags", [])
    seen = {t.get("name") for t in core_schema.get("tags", []) if isinstance(t.get("name"), str)}
    for tag in gateway_tags:
        name = tag.get("name") if isinstance(tag, dict) else None
        if isinstance(name, str) and name not in seen:
            core_schema.setdefault("tags", []).append(tag)
            seen.add(name)


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
                if not isinstance(operation, dict):
                    continue
                operation["security"] = (
                    [{"BearerAuth": []}] if (path, method.lower()) in protected_operations else []
                )

        gateway_schema = getattr(getattr(app, "state", None), "gateway_openapi_schema", None)
        if gateway_schema:
            _merge_gateway_openapi(openapi_schema, gateway_schema)

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
