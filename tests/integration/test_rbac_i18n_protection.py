from __future__ import annotations

import uuid

import httpx
import pytest


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def small_payload() -> dict:
    return {
        "key": f"test.small.{uuid.uuid4().hex[:8]}",
        "data": {"en": "Hello", "ru": "Privet", "uz": "Salom"},
    }


def large_payload() -> dict:
    return {
        "key1": f"test-{uuid.uuid4().hex[:6]}",
        "key2": "description",
        "data": {"en": "Hello", "ru": "Privet", "uz": "Salom"},
    }


def role_registry_payload() -> dict:
    return {
        "name": "Admin",
        "permissions": {},
    }


def missing_role_registry_payload() -> dict:
    return {
        "name": f"CustomRole{uuid.uuid4().hex[:6]}",
        "permissions": {"i18n_can_create_small": True},
    }


def permission_patch_payload() -> dict[str, bool]:
    return {"rbac_can_manage_permissions": False}


def role_create_payload() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return {
        "name": f"Role{suffix}",
        "title_key": f"role.custom.{suffix}.title",
    }


def role_update_payload() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return {
        "title_key": f"role.updated.{suffix}.title",
    }


def user_create_payload(role_id: int = 3) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:8]
    return {
        "username": f"user{suffix}",
        "password": "StrongPass123",
        "role_id": role_id,
    }


def user_update_payload() -> dict[str, object]:
    suffix = uuid.uuid4().hex[:8]
    return {
        "username": f"user{suffix}",
    }


def user_password_payload() -> dict[str, str]:
    return {"password": "EvenStronger123"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/rbac/roles", None),
        ("get", "/api/v1/rbac/roles/1", None),
        ("get", "/api/v1/rbac/users", None),
        ("get", "/api/v1/rbac/users/1", None),
        ("post", "/api/v1/rbac/roles", role_create_payload),
        ("patch", "/api/v1/rbac/roles/2", role_update_payload),
        ("delete", "/api/v1/rbac/roles/2", None),
        ("patch", "/api/v1/rbac/roles/2/permissions", permission_patch_payload),
        ("post", "/api/v1/rbac/roles/reset", None),
        ("post", "/api/v1/rbac/users", user_create_payload),
        ("patch", "/api/v1/rbac/users/1", user_update_payload),
        ("put", "/api/v1/rbac/users/1/password", user_password_payload),
        ("delete", "/api/v1/rbac/users/1", None),
        ("patch", "/api/v1/rbac/users/1/permissions", permission_patch_payload),
        ("post", "/api/v1/rbac/users/reset", None),
        ("post", "/api/v1/rbac/roles/role-registry/", role_registry_payload),
        ("get", "/api/v1/i18n/small", None),
        ("get", "/api/v1/i18n/large", None),
        ("put", "/api/v1/i18n/small", small_payload),
        ("put", "/api/v1/i18n/large", large_payload),
    ],
)
async def test_mutating_protected_endpoints_require_token(
    unauth_client: httpx.AsyncClient,
    method: str,
    path: str,
    payload,
):
    json_payload = payload() if callable(payload) else None
    response = await unauth_client.request(method.upper(), path, json=json_payload)
    assert response.status_code == 401, f"{method} {path}: {response.status_code} {response.text}"


@pytest.mark.asyncio
async def test_authenticated_user_can_access_read_endpoints(
    client: httpx.AsyncClient,
    regular_user_tokens: dict[str, str],
):
    headers = bearer_headers(regular_user_tokens["access"])
    readable_paths = [
        "/api/v1/i18n/small",
        "/api/v1/i18n/large",
        "/api/v1/rbac/roles",
        "/api/v1/rbac/users",
    ]
    for path in readable_paths:
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"


@pytest.mark.asyncio
async def test_bootstrap_seeds_default_role_title_translations(
    unauth_client: httpx.AsyncClient,
):
    login_response = await unauth_client.post(
        "/api/v1/auth/login",
        json={"username": "superuser", "password": "superuser11"},
    )
    assert login_response.status_code == 200, login_response.text
    access_token = login_response.json()["access_token"]

    response = await unauth_client.get(
        "/api/v1/i18n/small/role.super_admin.title",
        headers=bearer_headers(access_token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["key"] == "role.super_admin.title"
    assert isinstance(payload["data"], dict)
    assert payload["data"].get("en")


@pytest.mark.asyncio
async def test_regular_user_gets_403_on_permission_gated_endpoints(
    client: httpx.AsyncClient,
    regular_user_tokens: dict[str, str],
):
    headers = bearer_headers(regular_user_tokens["access"])
    cases = [
        # Keep this set representative across RBAC and i18n mutating permissions.
        ("POST", "/api/v1/rbac/roles", role_create_payload()),
        ("PATCH", "/api/v1/rbac/roles/2/permissions", permission_patch_payload()),
        ("POST", "/api/v1/rbac/users", user_create_payload()),
        ("POST", "/api/v1/rbac/users/reset", None),
        ("PUT", "/api/v1/i18n/small", small_payload()),
        (
            "PATCH",
            f"/api/v1/rbac/users/{regular_user_tokens['user_id']}/permissions",
            permission_patch_payload(),
        ),
    ]

    for method, path, payload in cases:
        response = await client.request(method, path, headers=headers, json=payload)
        assert response.status_code == 403, f"{method} {path}: {response.status_code} {response.text}"


@pytest.mark.asyncio
async def test_superuser_can_access_protected_mutating_endpoints(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
    regular_user_tokens: dict[str, str],
):
    headers = bearer_headers(superuser_tokens["access"])

    role_registry_response = await client.post(
        "/api/v1/rbac/roles/role-registry/",
        headers=headers,
        json=role_registry_payload(),
    )
    assert role_registry_response.status_code == 200, role_registry_response.text

    patch_role_response = await client.patch(
        "/api/v1/rbac/roles/2/permissions",
        headers=headers,
        json=permission_patch_payload(),
    )
    assert patch_role_response.status_code == 200, patch_role_response.text

    patch_user_response = await client.patch(
        f"/api/v1/rbac/users/{regular_user_tokens['user_id']}/permissions",
        headers=headers,
        json=permission_patch_payload(),
    )
    assert patch_user_response.status_code == 200, patch_user_response.text

    reset_users_response = await client.post("/api/v1/rbac/users/reset", headers=headers)
    assert reset_users_response.status_code == 200, reset_users_response.text

    upsert_small_response = await client.put(
        "/api/v1/i18n/small",
        headers=headers,
        json=small_payload(),
    )
    assert upsert_small_response.status_code == 200, upsert_small_response.text


@pytest.mark.asyncio
async def test_superuser_can_manage_roles_and_users_crud(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    headers = bearer_headers(superuser_tokens["access"])

    create_role_response = await client.post(
        "/api/v1/rbac/roles",
        headers=headers,
        json=role_create_payload(),
    )
    assert create_role_response.status_code == 201, create_role_response.text
    created_role = create_role_response.json()
    assert created_role["name"].startswith("Role")
    assert created_role["title_key"].startswith("role.custom.")

    patch_role_response = await client.patch(
        f"/api/v1/rbac/roles/{created_role['id']}",
        headers=headers,
        json=role_update_payload(),
    )
    assert patch_role_response.status_code == 200, patch_role_response.text
    patched_role = patch_role_response.json()
    assert patched_role["id"] == created_role["id"]
    assert patched_role["title_key"].startswith("role.updated.")

    create_user_response = await client.post(
        "/api/v1/rbac/users",
        headers=headers,
        json=user_create_payload(role_id=created_role["id"]),
    )
    assert create_user_response.status_code == 201, create_user_response.text
    created_user = create_user_response.json()
    assert created_user["id"] > 0
    assert created_user["role_id"] == created_role["id"]
    assert created_user["username"].startswith("user")

    patch_user_response = await client.patch(
        f"/api/v1/rbac/users/{created_user['id']}",
        headers=headers,
        json=user_update_payload(),
    )
    assert patch_user_response.status_code == 200, patch_user_response.text
    patched_user = patch_user_response.json()
    assert patched_user["id"] == created_user["id"]
    assert patched_user["username"].startswith("user")

    password_response = await client.put(
        f"/api/v1/rbac/users/{created_user['id']}/password",
        headers=headers,
        json=user_password_payload(),
    )
    assert password_response.status_code == 200, password_response.text

    delete_user_response = await client.delete(
        f"/api/v1/rbac/users/{created_user['id']}",
        headers=headers,
    )
    assert delete_user_response.status_code == 204, delete_user_response.text

    delete_role_response = await client.delete(
        f"/api/v1/rbac/roles/{created_role['id']}",
        headers=headers,
    )
    assert delete_role_response.status_code == 204, delete_role_response.text


@pytest.mark.asyncio
async def test_role_delete_returns_409_when_role_is_in_use(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    headers = bearer_headers(superuser_tokens["access"])

    create_role_response = await client.post(
        "/api/v1/rbac/roles",
        headers=headers,
        json=role_create_payload(),
    )
    assert create_role_response.status_code == 201, create_role_response.text
    created_role = create_role_response.json()

    create_user_response = await client.post(
        "/api/v1/rbac/users",
        headers=headers,
        json=user_create_payload(role_id=created_role["id"]),
    )
    assert create_user_response.status_code == 201, create_user_response.text

    delete_role_response = await client.delete(
        f"/api/v1/rbac/roles/{created_role['id']}",
        headers=headers,
    )
    assert delete_role_response.status_code == 409, delete_role_response.text


@pytest.mark.asyncio
async def test_superuser_cannot_delete_self_via_admin_delete(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    headers = bearer_headers(superuser_tokens["access"])
    me_response = await client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200, me_response.text
    me = me_response.json()

    delete_response = await client.delete(f"/api/v1/rbac/users/{me['id']}", headers=headers)
    assert delete_response.status_code == 403, delete_response.text


@pytest.mark.asyncio
async def test_crud_endpoints_reject_permissions_field(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    headers = bearer_headers(superuser_tokens["access"])
    role_payload = role_create_payload()
    role_payload["permissions"] = {}
    role_response = await client.post("/api/v1/rbac/roles", headers=headers, json=role_payload)
    assert role_response.status_code in {400, 422}, role_response.text

    user_payload = user_create_payload()
    user_payload["permissions"] = {}
    user_response = await client.post("/api/v1/rbac/users", headers=headers, json=user_payload)
    assert user_response.status_code in {400, 422}, user_response.text


@pytest.mark.asyncio
async def test_role_registry_returns_404_for_missing_role(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    headers = bearer_headers(superuser_tokens["access"])
    response = await client.post(
        "/api/v1/rbac/roles/role-registry/",
        headers=headers,
        json=missing_role_registry_payload(),
    )
    assert response.status_code == 404, response.text
