from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from src.utils.inprocess_http import InternalAwareHttpClient, get_internal_http_client


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get_app_from_client(client: httpx.AsyncClient) -> FastAPI:
    transport = getattr(client, "_transport", None)
    app = getattr(transport, "app", None)
    assert isinstance(app, FastAPI), "Expected httpx ASGITransport with FastAPI app"
    return app


def _ensure_internal_proxy_route(app: FastAPI) -> None:
    if getattr(app.state, "_test_internal_proxy_route_added", False):
        return

    @app.get("/api/test/internal-me")
    async def _internal_me(
        internal_client: InternalAwareHttpClient = Depends(get_internal_http_client),
    ) -> dict[str, Any]:
        response = await internal_client.get("/api/v1/auth/me")
        return {
            "status_code": response.status_code,
            "payload": response.json(),
        }

    app.state._test_internal_proxy_route_added = True


@pytest.mark.asyncio
async def test_inprocess_dependency_client_forwards_bearer_to_protected_endpoint(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    app = _get_app_from_client(client)
    _ensure_internal_proxy_route(app)

    response = await client.get(
        "/api/test/internal-me",
        headers=bearer_headers(superuser_tokens["access"]),
    )
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["status_code"] == 200
    assert data["payload"]["username"] == "superuser"
    assert "role" in data["payload"]
