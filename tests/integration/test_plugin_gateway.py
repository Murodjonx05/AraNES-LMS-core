"""Integration tests for the plugin gateway: in-process plugins mounted under /api/plugins/{name}."""
from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from src.config import build_app_config
from src.plugins import clear_plugin_registry, register_plugin
from src.plugins.demo import get_demo_plugin
from src.runtime import build_runtime, reset_default_runtime


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def app_with_demo_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seeded_db_template: Path):
    """Build an app with the demo plugin registered and a per-test DB copy."""
    db_path = tmp_path / "plugin_test.sqlite3"
    shutil.copy2(seeded_db_template, db_path)

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
    monkeypatch.setenv("PBKDF2_ITERATIONS", "1")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("BOOTSTRAP_SUPERUSER_CREATE", "false")

    clear_plugin_registry()
    register_plugin(get_demo_plugin())

    reset_default_runtime()
    config = build_app_config()
    runtime = build_runtime(config)
    from src.app import create_app
    app = create_app(runtime)

    try:
        yield app
    finally:
        clear_plugin_registry()
        await runtime.engine.dispose()
        reset_default_runtime()


@pytest.mark.asyncio
async def test_plugin_route_requires_auth(app_with_demo_plugin):
    """Plugin routes require Bearer token (401 without)."""
    transport = httpx.ASGITransport(app=app_with_demo_plugin)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/plugins/demo/")
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_plugin_route_returns_payload_with_token(app_with_demo_plugin):
    """With valid token, plugin route returns 200 and expected payload."""
    transport = httpx.ASGITransport(app=app_with_demo_plugin)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "superuser", "password": "superuser11"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        response = await client.get("/api/plugins/demo/", headers=_bearer_headers(token))
    assert response.status_code == 200, response.text
    assert response.json() == {"plugin": "demo", "status": "ok"}
    assert response.headers.get("X-Request-ID")