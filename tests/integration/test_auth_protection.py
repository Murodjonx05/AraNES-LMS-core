from __future__ import annotations

import httpx
import pytest
import uuid


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


@pytest.mark.asyncio
async def test_login_me_and_reset_access_flow(client: httpx.AsyncClient):
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"username": "superuser", "password": "superuser11"},
    )
    assert login_response.status_code == 200, login_response.text
    tokens = login_response.json()
    access_token = tokens["access_token"]
    me_response = await client.get(
        "/api/v1/auth/me",
        headers=bearer_headers(access_token),
    )
    assert me_response.status_code == 200, me_response.text
    assert me_response.json()["username"] == "superuser"

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


@pytest.mark.asyncio
async def test_me_uses_stable_user_id_claim_after_username_change_and_reuse(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    original_username = f"user{uuid.uuid4().hex[:8]}"
    renamed_username = f"user{uuid.uuid4().hex[:8]}"

    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"username": original_username, "password": "StrongPass123"},
    )
    assert signup_response.status_code == 201, signup_response.text
    access_token = signup_response.json()["access_token"]

    me_before_rename = await client.get("/api/v1/auth/me", headers=bearer_headers(access_token))
    assert me_before_rename.status_code == 200, me_before_rename.text
    user_id = me_before_rename.json()["id"]

    admin_headers = bearer_headers(superuser_tokens["access"])
    rename_response = await client.patch(
        f"/api/v1/rbac/users/{user_id}",
        headers=admin_headers,
        json={"username": renamed_username},
    )
    assert rename_response.status_code == 200, rename_response.text
    assert rename_response.json()["username"] == renamed_username

    recreate_old_username = await client.post(
        "/api/v1/rbac/users",
        headers=admin_headers,
        json={"username": original_username, "password": "StrongPass123", "role_id": 6},
    )
    assert recreate_old_username.status_code == 201, recreate_old_username.text

    me_after_rename = await client.get("/api/v1/auth/me", headers=bearer_headers(access_token))
    assert me_after_rename.status_code == 200, me_after_rename.text
    payload = me_after_rename.json()
    assert payload["id"] == user_id
    assert payload["username"] == renamed_username
