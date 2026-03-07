from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from src.i18n.cache import I18nCacheService, build_large_cache_key, build_small_cache_key
from src.utils.cache import RedisCacheService


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


class _FailingRedis:
    async def get(self, key: str):
        raise RuntimeError("redis unavailable")

    async def set(self, key: str, value: str, ex: int):
        return None

    async def delete(self, key: str):
        return None

    async def ping(self):
        return True

    async def aclose(self):
        return None


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_i18n_cache_key_builders_are_stable():
    assert build_small_cache_key("role.super_admin.title") == "i18n:small:role.super_admin.title"
    assert build_large_cache_key("course", "description") == "i18n:large:course:description"


@pytest.mark.asyncio
async def test_i18n_cache_service_wraps_generic_backend():
    backend = _FakeCache()
    service = I18nCacheService(backend=backend)

    await service.set_small("hello", {"key": "hello", "data": {"en": "Hello"}})
    payload = await service.get_small("hello")
    await service.invalidate_small("hello")

    assert payload == {"key": "hello", "data": {"en": "Hello"}}
    assert backend.deleted == ["i18n:small:hello"]


@pytest.mark.asyncio
async def test_i18n_small_read_works_from_db_when_redis_disabled(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    response = await client.get(
        "/api/v1/i18n/small/role.super_admin.title",
        headers=_auth_headers(superuser_tokens["access"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["key"] == "role.super_admin.title"


@pytest.mark.asyncio
async def test_i18n_small_read_populates_cache_and_next_read_uses_it(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _get_runtime(client)
    fake_cache = _FakeCache()
    runtime.cache_service = fake_cache

    first = await client.get(
        "/api/v1/i18n/small/role.super_admin.title",
        headers=_auth_headers(superuser_tokens["access"]),
    )
    assert first.status_code == 200, first.text
    assert build_small_cache_key("role.super_admin.title") in fake_cache.values

    monkeypatch.setattr(
        "src.i18n.endpoints.small.crud_get_small_by_key",
        AsyncMock(side_effect=AssertionError("DB should not be used on cache hit")),
    )

    second = await client.get(
        "/api/v1/i18n/small/role.super_admin.title",
        headers=_auth_headers(superuser_tokens["access"]),
    )
    assert second.status_code == 200, second.text
    assert second.json() == first.json()


@pytest.mark.asyncio
async def test_i18n_large_write_invalidates_cache(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    runtime = _get_runtime(client)
    fake_cache = _FakeCache()
    fake_cache.values[build_large_cache_key("course-cache", "description")] = {
        "key1": "course-cache",
        "key2": "description",
        "data": {"en": "Old"},
    }
    runtime.cache_service = fake_cache

    response = await client.put(
        "/api/v1/i18n/large",
        headers=_auth_headers(superuser_tokens["access"]),
        json={
            "key1": "course-cache",
            "key2": "description",
            "data": {"en": "New"},
        },
    )
    assert response.status_code == 200, response.text
    assert build_large_cache_key("course-cache", "description") in fake_cache.deleted


@pytest.mark.asyncio
async def test_i18n_small_read_falls_back_to_db_when_redis_fails(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
):
    runtime = _get_runtime(client)
    cache_service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=False,
        heartbeat_schedule_seconds=(60,),
    )
    cache_service.client = _FailingRedis()
    cache_service._available = True
    runtime.cache_service = cache_service

    response = await client.get(
        "/api/v1/i18n/small/role.super_admin.title",
        headers=_auth_headers(superuser_tokens["access"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["key"] == "role.super_admin.title"
    assert cache_service.is_available() is False
