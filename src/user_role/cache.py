from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Depends

from src.utils.cache import RedisCacheService, get_request_cache_service


class JsonCacheBackend(Protocol):
    async def get_json(self, key: str) -> dict[str, Any] | None: ...

    async def set_json(
        self,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None: ...

    async def delete(self, key: str) -> None: ...


def build_role_cache_key(role_id: int) -> str:
    return f"rbac:role:{role_id}"


def build_role_list_cache_key() -> str:
    return "rbac:role:list"


def build_user_cache_key(user_id: int) -> str:
    return f"rbac:user:{user_id}"


def build_user_list_cache_key() -> str:
    return "rbac:user:list"


@dataclass(slots=True)
class RbacCacheService:
    backend: JsonCacheBackend

    async def get_role(self, role_id: int) -> dict[str, Any] | None:
        return await self.backend.get_json(build_role_cache_key(role_id))

    async def set_role(
        self,
        role_id: int,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_role_cache_key(role_id), payload, ttl_seconds)

    async def invalidate_role(self, role_id: int) -> None:
        await self.backend.delete(build_role_cache_key(role_id))

    async def get_role_list(self) -> list[dict[str, Any]] | None:
        payload = await self.backend.get_json(build_role_list_cache_key())
        if not isinstance(payload, dict):
            return None
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        return items

    async def set_role_list(
        self,
        items: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_role_list_cache_key(), {"items": items}, ttl_seconds)

    async def invalidate_role_list(self) -> None:
        await self.backend.delete(build_role_list_cache_key())

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.backend.get_json(build_user_cache_key(user_id))

    async def set_user(
        self,
        user_id: int,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_user_cache_key(user_id), payload, ttl_seconds)

    async def invalidate_user(self, user_id: int) -> None:
        await self.backend.delete(build_user_cache_key(user_id))

    async def get_user_list(self) -> list[dict[str, Any]] | None:
        payload = await self.backend.get_json(build_user_list_cache_key())
        if not isinstance(payload, dict):
            return None
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        return items

    async def set_user_list(
        self,
        items: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_user_list_cache_key(), {"items": items}, ttl_seconds)

    async def invalidate_user_list(self) -> None:
        await self.backend.delete(build_user_list_cache_key())


def get_request_rbac_cache_service(
    cache_service: RedisCacheService = Depends(get_request_cache_service),
) -> RbacCacheService:
    return RbacCacheService(backend=cache_service)


__all__ = [
    "JsonCacheBackend",
    "RbacCacheService",
    "build_role_cache_key",
    "build_role_list_cache_key",
    "build_user_cache_key",
    "build_user_list_cache_key",
    "get_request_rbac_cache_service",
]
