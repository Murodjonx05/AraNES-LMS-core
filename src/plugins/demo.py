"""Minimal in-process demo plugin for tests and local dev."""
from __future__ import annotations

from fastapi import APIRouter

from src.plugins import Plugin

demo_router = APIRouter()


@demo_router.get("/", summary="Demo plugin root")
def demo_root():
    """Return a fixed payload to confirm the plugin is mounted."""
    return {"plugin": "demo", "status": "ok"}


def get_demo_plugin() -> Plugin:
    return Plugin(name="demo", router=demo_router)
