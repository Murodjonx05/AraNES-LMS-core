from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from src.user_role.cache import (
    RbacCacheService,
    build_role_cache_key,
    build_role_list_cache_key,
    build_user_cache_key,
    build_user_list_cache_key,
)


def _get_runtime(client: httpx.AsyncClient):
    transport = getattr(client, "_transport", None)
    app = getattr(transport, "app", None)
    assert app is not None
    runtime = getattr(app.state, "runtime", None)
    assert runtime is not None
    return runtime


class _FakeCache:
    def __init__(self):
        self.values: dict[str, dict] = {}
        self.deleted: list[str] = []

    async def get_json(self, key: str):
        return self.values.get(key)

    async def set_json(self, key: str, payload: dict, ttl_seconds: int | None = None):
        self.values[key] = payload

    async def delete(self, key: str):
        self.deleted.append(key)
        self.values.pop(key, None)

    async def close(self):
        return None


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_rbac_cache_service_wraps_generic_backend():
    backend = _FakeCache()
    service = RbacCacheService(backend=backend)

    role_payload = {"id": 1, "name": "SuperAdmin", "title_key": "role.super_admin.title", "permissions": {}}
    user_payload = {"id": 1, "username": "superuser", "role_id": 1, "permissions": {}}

    await service.set_role_list([role_payload])
    await service.set_role(1, role_payload)
    await service.set_user_list([user_payload])
    await service.set_user(1, user_payload)

    assert await service.get_role_list() == [role_payload]
    assert await service.get_role(1) == role_payload
    assert await service.get_user_list() == [user_payload]
    assert await service.get_user(1) == user_payload


@pytest.mark.asyncio
async def test_rbac_roles_list_read_populates_cache_and_role_write_invalidates_only_role_keys(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _get_runtime(client)
    fake_cache = _FakeCache()
    fake_cache.values[build_user_list_cache_key()] = {"items": [{"id": 1, "username": "superuser"}]}
    runtime.cache_service = fake_cache

    first = await client.get("/api/v1/rbac/roles", headers=_auth_headers(superuser_tokens["access"]))
    assert first.status_code == 200, first.text
    assert build_role_list_cache_key() in fake_cache.values

    monkeypatch.setattr(
        "src.user_role.endpoints.roles.crud_list_roles",
        AsyncMock(side_effect=AssertionError("DB should not be used on role list cache hit")),
    )

    second = await client.get("/api/v1/rbac/roles", headers=_auth_headers(superuser_tokens["access"]))
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    response = await client.patch(
        "/api/v1/rbac/roles/2/permissions",
        headers=_auth_headers(superuser_tokens["access"]),
        json={"rbac_can_manage_permissions": False},
    )
    assert response.status_code == 200, response.text
    assert build_role_list_cache_key() in fake_cache.deleted
    assert build_user_list_cache_key() not in fake_cache.deleted
    assert build_role_cache_key(2) in fake_cache.values or build_role_cache_key(2) in fake_cache.deleted


@pytest.mark.asyncio
async def test_rbac_users_list_read_populates_cache_and_user_write_invalidates_only_user_keys(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
    regular_user_tokens: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _get_runtime(client)
    fake_cache = _FakeCache()
    fake_cache.values[build_role_list_cache_key()] = {"items": [{"id": 1, "name": "SuperAdmin"}]}
    runtime.cache_service = fake_cache

    first = await client.get("/api/v1/rbac/users", headers=_auth_headers(superuser_tokens["access"]))
    assert first.status_code == 200, first.text
    assert build_user_list_cache_key() in fake_cache.values

    monkeypatch.setattr(
        "src.user_role.endpoints.users.crud_list_users",
        AsyncMock(side_effect=AssertionError("DB should not be used on user list cache hit")),
    )

    second = await client.get("/api/v1/rbac/users", headers=_auth_headers(superuser_tokens["access"]))
    assert second.status_code == 200, second.text
    assert second.json() == first.json()

    response = await client.patch(
        f"/api/v1/rbac/users/{regular_user_tokens['user_id']}/permissions",
        headers=_auth_headers(superuser_tokens["access"]),
        json={"rbac_can_manage_permissions": False},
    )
    assert response.status_code == 200, response.text
    assert build_user_list_cache_key() in fake_cache.deleted
    assert build_role_list_cache_key() not in fake_cache.deleted
    assert (
        build_user_cache_key(regular_user_tokens["user_id"]) in fake_cache.values
        or build_user_cache_key(regular_user_tokens["user_id"]) in fake_cache.deleted
    )


@pytest.mark.asyncio
async def test_schema_invalid_rbac_cache_entries_are_deleted_and_fall_back_to_db(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    runtime = _get_runtime(client)
    fake_cache = _FakeCache()
    fake_cache.values[build_role_cache_key(1)] = {"id": 2, "name": "Wrong", "title_key": "wrong"}
    fake_cache.values[build_role_list_cache_key()] = {"items": [{"id": "wrong-type"}]}
    runtime.cache_service = fake_cache

    item_response = await client.get("/api/v1/rbac/roles/1", headers=_auth_headers(superuser_tokens["access"]))
    assert item_response.status_code == 200, item_response.text
    assert item_response.json()["id"] == 1

    list_response = await client.get("/api/v1/rbac/roles", headers=_auth_headers(superuser_tokens["access"]))
    assert list_response.status_code == 200, list_response.text
    assert isinstance(list_response.json(), list)

    assert build_role_cache_key(1) in fake_cache.deleted
    assert build_role_list_cache_key() in fake_cache.deleted
