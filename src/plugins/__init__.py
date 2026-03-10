"""Minimal plugin system: register FastAPI routers under /api/plugins/{name}."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

__all__ = ["Plugin", "plugin_registry", "register_plugin"]


@dataclass(frozen=True)
class Plugin:
    """In-process plugin: a named router mounted under /api/plugins/{name}."""
    name: str
    router: APIRouter


_plugin_registry: list[Plugin] = []


def plugin_registry() -> list[Plugin]:
    """Return the current list of registered plugins (read-only)."""
    return list(_plugin_registry)


def register_plugin(plugin: Plugin) -> None:
    """Register a plugin. Call before the app includes routes (e.g. at import or in lifespan)."""
    if any(p.name == plugin.name for p in _plugin_registry):
        raise ValueError(f"Plugin already registered: {plugin.name}")
    _plugin_registry.append(plugin)


def clear_plugin_registry() -> None:
    """Remove all plugins. Intended for tests."""
    _plugin_registry.clear()
