from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Depends
from pydantic import TypeAdapter, ValidationError

from src.user_role.schemas import RoleResponseSchema, UserResponseSchema
from src.utils.cache import RedisCacheService, get_request_cache_service

_ROLE_LIST_ADAPTER = TypeAdapter(list[RoleResponseSchema])
_USER_LIST_ADAPTER = TypeAdapter(list[UserResponseSchema])


def _serialize_model_list(items: list[RoleResponseSchema] | list[UserResponseSchema]) -> list[dict[str, Any]]:
    return [item.model_dump() for item in items]


def _ids_are_strictly_increasing(items: list[RoleResponseSchema] | list[UserResponseSchema]) -> bool:
    previous_id: int | None = None
    for item in items:
        if previous_id is not None and item.id <= previous_id:
            return False
        previous_id = item.id
    return True


def _normalize_role_item(payload: Any, *, expected_role_id: int | None = None) -> dict[str, Any] | None:
    try:
        item = RoleResponseSchema.model_validate(payload)
    except ValidationError:
        return None
    if expected_role_id is not None and item.id != expected_role_id:
        return None
    return item.model_dump()


def _normalize_user_item(payload: Any, *, expected_user_id: int | None = None) -> dict[str, Any] | None:
    try:
        item = UserResponseSchema.model_validate(payload)
    except ValidationError:
        return None
    if expected_user_id is not None and item.id != expected_user_id:
        return None
    return item.model_dump()


def _normalize_role_list(payload: Any) -> list[dict[str, Any]] | None:
    try:
        items = _ROLE_LIST_ADAPTER.validate_python(payload)
    except ValidationError:
        return None
    if not _ids_are_strictly_increasing(items):
        return None
    return _serialize_model_list(items)


def _normalize_user_list(payload: Any) -> list[dict[str, Any]] | None:
    try:
        items = _USER_LIST_ADAPTER.validate_python(payload)
    except ValidationError:
        return None
    if not _ids_are_strictly_increasing(items):
        return None
    return _serialize_model_list(items)


class JsonCacheBackend(Protocol):
    async def get_json(self, key: str) -> dict[str, Any] | None: ...

    async def set_json(
        self,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def delete_many(self, keys: list[str]) -> None: ...


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

    async def _delete_keys(self, keys: Iterable[str]) -> None:
        cache_keys = list(dict.fromkeys(keys))
        if not cache_keys:
            return
        delete_many = getattr(self.backend, "delete_many", None)
        if callable(delete_many):
            await delete_many(cache_keys)
            return
        for cache_key in cache_keys:
            await self.backend.delete(cache_key)

    async def get_role(self, role_id: int) -> dict[str, Any] | None:
        payload = await self.backend.get_json(build_role_cache_key(role_id))
        if payload is None:
            return None
        normalized_item = _normalize_role_item(payload, expected_role_id=role_id)
        if normalized_item is None:
            await self.invalidate_role(role_id)
            return None
        return normalized_item

    async def set_role(
        self,
        role_id: int,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_role_cache_key(role_id), payload, ttl_seconds)

    async def invalidate_role(self, role_id: int) -> None:
        await self.backend.delete(build_role_cache_key(role_id))

    async def invalidate_roles(
        self,
        role_ids: Iterable[int],
        *,
        include_list: bool = False,
    ) -> None:
        keys = [build_role_cache_key(role_id) for role_id in role_ids]
        if include_list:
            keys.append(build_role_list_cache_key())
        await self._delete_keys(keys)

    async def get_role_list(self) -> list[dict[str, Any]] | None:
        payload = await self.backend.get_json(build_role_list_cache_key())
        if payload is None:
            return None
        if not isinstance(payload, dict):
            await self.invalidate_role_list()
            return None
        items = payload.get("items")
        normalized_items = _normalize_role_list(items)
        if normalized_items is None:
            await self.invalidate_role_list()
            return None
        return normalized_items

    async def set_role_list(
        self,
        items: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_role_list_cache_key(), {"items": items}, ttl_seconds)

    async def invalidate_role_list(self) -> None:
        await self.backend.delete(build_role_list_cache_key())

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        payload = await self.backend.get_json(build_user_cache_key(user_id))
        if payload is None:
            return None
        normalized_item = _normalize_user_item(payload, expected_user_id=user_id)
        if normalized_item is None:
            await self.invalidate_user(user_id)
            return None
        return normalized_item

    async def set_user(
        self,
        user_id: int,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_user_cache_key(user_id), payload, ttl_seconds)

    async def invalidate_user(self, user_id: int) -> None:
        await self.backend.delete(build_user_cache_key(user_id))

    async def invalidate_users(
        self,
        user_ids: Iterable[int],
        *,
        include_list: bool = False,
    ) -> None:
        keys = [build_user_cache_key(user_id) for user_id in user_ids]
        if include_list:
            keys.append(build_user_list_cache_key())
        await self._delete_keys(keys)

    async def get_user_list(self) -> list[dict[str, Any]] | None:
        payload = await self.backend.get_json(build_user_list_cache_key())
        if payload is None:
            return None
        if not isinstance(payload, dict):
            await self.invalidate_user_list()
            return None
        items = payload.get("items")
        normalized_items = _normalize_user_list(items)
        if normalized_items is None:
            await self.invalidate_user_list()
            return None
        return normalized_items

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
