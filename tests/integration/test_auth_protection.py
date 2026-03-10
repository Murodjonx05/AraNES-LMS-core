from __future__ import annotations

import httpx
import pytest
import uuid

from src.user_role.models import User
from src.user_role.defaults import DEFAULT_SIGNUP_ROLE_ID


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _runtime_from_client(client: httpx.AsyncClient):
    transport = getattr(client, "_transport", None)
    app = getattr(transport, "app", None)
    assert app is not None
    runtime = getattr(app.state, "runtime", None)
    assert runtime is not None
    return runtime


@pytest.mark.asyncio
async def test_me_requires_access_token(unauth_client: httpx.AsyncClient):
    response = await unauth_client.get("/api/v1/auth/me")
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_me_rejects_invalid_bearer(unauth_client: httpx.AsyncClient):
    response = await unauth_client.get(
        "/api/v1/auth/me",
        headers=bearer_headers("not-a-valid-token"),
    )
    assert response.status_code == 401, response.text
    body = response.json()
    assert "message" in body
    assert body.get("error_type", "").endswith("JWTDecodeError") or "token" in body.get("message", "").lower()
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_authenticated_me_completes_quickly(client: httpx.AsyncClient):
    """Sanity check: authenticated request should complete without obvious regression."""
    import time

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "superuser", "password": "superuser11"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    start = time.perf_counter()
    resp = await client.get("/api/v1/auth/me", headers=bearer_headers(token))
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 2000, f"Authenticated /me took {elapsed_ms:.0f}ms (expected < 2000ms)"


@pytest.mark.asyncio
async def test_login_me_and_reset_access_flow(client: httpx.AsyncClient):
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "superuser", "password": "superuser11"},
    )
    assert login_response.status_code == 200, login_response.text
    tokens = login_response.json()
    access_token = tokens["access_token"]

    no_token_reset = await client.post("/api/v1/auth/reset")
    assert no_token_reset.status_code == 401, no_token_reset.text

    reset_response = await client.post(
        "/api/v1/auth/reset",
        headers=bearer_headers(access_token),
    )
    assert reset_response.status_code == 200, reset_response.text
    assert "revoked" in reset_response.json()["message"].lower()

    reused_access_reset = await client.post(
        "/api/v1/auth/reset",
        headers=bearer_headers(access_token),
    )
    assert reused_access_reset.status_code == 401, reused_access_reset.text

    me_with_revoked_token = await client.get(
        "/api/v1/auth/me",
        headers=bearer_headers(access_token),
    )
    assert me_with_revoked_token.status_code == 401, me_with_revoked_token.text

    relogin_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "superuser", "password": "superuser11"},
    )
    assert relogin_response.status_code == 200, relogin_response.text
    new_access_token = relogin_response.json()["access_token"]
    assert new_access_token != access_token

    me_after_relogin = await client.get(
        "/api/v1/auth/me",
        headers=bearer_headers(new_access_token),
    )
    assert me_after_relogin.status_code == 200, me_after_relogin.text
    assert me_after_relogin.json()["username"] == "superuser"


@pytest.mark.asyncio
async def test_me_uses_stable_user_id_claim_after_username_change_and_reuse(
    client: httpx.AsyncClient,
    user_tokens_factory,
):
    original_username = f"user{uuid.uuid4().hex[:8]}"
    renamed_username = f"user{uuid.uuid4().hex[:8]}"
    user_tokens = await user_tokens_factory(
        username=original_username,
        role_id=DEFAULT_SIGNUP_ROLE_ID,
    )
    access_token = user_tokens["access"]
    user_id = user_tokens["user_id"]
    runtime = _runtime_from_client(client)
    async with runtime.session_factory() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None
        db_user.username = renamed_username
        session.add(
            User(
                username=original_username,
                password="fixture-only",
                role_id=DEFAULT_SIGNUP_ROLE_ID,
                permissions={},
            )
        )
        await session.commit()

    me_after_rename = await client.get("/api/v1/auth/me", headers=bearer_headers(access_token))
    assert me_after_rename.status_code == 200, me_after_rename.text
    payload = me_after_rename.json()
    assert payload["id"] == user_id
    assert payload["username"] == renamed_username
