from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends

from src.utils.cache import RedisCacheService, get_request_cache_service


def build_small_cache_key(key: str) -> str:
    return f"i18n:small:{key}"


def build_large_cache_key(key1: str, key2: str) -> str:
    return f"i18n:large:{key1}:{key2}"


@dataclass(slots=True)
class I18nCacheService:
    backend: RedisCacheService

    async def get_small(self, key: str) -> dict[str, Any] | None:
        return await self.backend.get_json(build_small_cache_key(key))

    async def set_small(
        self,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_small_cache_key(key), payload, ttl_seconds)

    async def invalidate_small(self, key: str) -> None:
        await self.backend.delete(build_small_cache_key(key))

    async def get_large(self, key1: str, key2: str) -> dict[str, Any] | None:
        return await self.backend.get_json(build_large_cache_key(key1, key2))

    async def set_large(
        self,
        key1: str,
        key2: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_large_cache_key(key1, key2), payload, ttl_seconds)

    async def invalidate_large(self, key1: str, key2: str) -> None:
        await self.backend.delete(build_large_cache_key(key1, key2))


def get_request_i18n_cache_service(
    cache_service: RedisCacheService = Depends(get_request_cache_service),
) -> I18nCacheService:
    return I18nCacheService(backend=cache_service)
