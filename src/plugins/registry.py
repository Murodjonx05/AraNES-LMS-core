"""Build a router that mounts registered plugin routers under /api. Used from create_app."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.auth.dependencies import require_access_token_payload
from src.plugins import plugin_registry


def build_plugin_router() -> APIRouter:
    """Return a new APIRouter with prefix /api that includes all registered plugins under /api/plugins/{name}."""
    router = APIRouter(prefix="/api")
    for plugin in plugin_registry():
        router.include_router(
            plugin.router,
            prefix=f"/plugins/{plugin.name}",
            tags=["plugins", plugin.name],
            dependencies=[Depends(require_access_token_payload)],
        )
    return router
