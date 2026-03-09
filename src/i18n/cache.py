from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends
from pydantic import TypeAdapter, ValidationError

from src.i18n.schemas import I18nLargeSchema, I18nSmallSchema
from src.utils.cache import RedisCacheService, get_request_cache_service

_SMALL_LIST_ADAPTER = TypeAdapter(list[I18nSmallSchema])
_LARGE_LIST_ADAPTER = TypeAdapter(list[I18nLargeSchema])


def _serialize_model_list(items: list[I18nSmallSchema] | list[I18nLargeSchema]) -> list[dict[str, Any]]:
    return [item.model_dump() for item in items]


def _small_keys_are_strictly_increasing(items: list[I18nSmallSchema]) -> bool:
    previous_key: str | None = None
    for item in items:
        if previous_key is not None and item.key <= previous_key:
            return False
        previous_key = item.key
    return True


def _large_keys_are_strictly_increasing(items: list[I18nLargeSchema]) -> bool:
    previous_key: tuple[str, str] | None = None
    for item in items:
        current_key = (item.key1, item.key2)
        if previous_key is not None and current_key <= previous_key:
            return False
        previous_key = current_key
    return True


def _normalize_small_item(payload: Any, *, expected_key: str | None = None) -> dict[str, Any] | None:
    try:
        item = I18nSmallSchema.model_validate(payload)
    except ValidationError:
        return None
    if expected_key is not None and item.key != expected_key:
        return None
    return item.model_dump()


def _normalize_large_item(
    payload: Any,
    *,
    expected_key1: str | None = None,
    expected_key2: str | None = None,
) -> dict[str, Any] | None:
    try:
        item = I18nLargeSchema.model_validate(payload)
    except ValidationError:
        return None
    if expected_key1 is not None and item.key1 != expected_key1:
        return None
    if expected_key2 is not None and item.key2 != expected_key2:
        return None
    return item.model_dump()


def _normalize_small_list(payload: Any) -> list[dict[str, Any]] | None:
    try:
        items = _SMALL_LIST_ADAPTER.validate_python(payload)
    except ValidationError:
        return None
    if not _small_keys_are_strictly_increasing(items):
        return None
    return _serialize_model_list(items)


def _normalize_large_list(payload: Any) -> list[dict[str, Any]] | None:
    try:
        items = _LARGE_LIST_ADAPTER.validate_python(payload)
    except ValidationError:
        return None
    if not _large_keys_are_strictly_increasing(items):
        return None
    return _serialize_model_list(items)


def build_small_cache_key(key: str) -> str:
    return f"i18n:small:{key}"


def build_small_list_cache_key() -> str:
    return "i18n:small:list"


def build_large_cache_key(key1: str, key2: str) -> str:
    return f"i18n:large:{len(key1)}:{key1}|{len(key2)}:{key2}"


def build_large_list_cache_key() -> str:
    return "i18n:large:list"


@dataclass(slots=True)
class I18nCacheService:
    backend: RedisCacheService

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

    async def get_small_list(self) -> list[dict[str, Any]] | None:
        payload = await self.backend.get_json(build_small_list_cache_key())
        if payload is None:
            return None
        if not isinstance(payload, dict):
            await self.invalidate_small_list()
            return None
        items = payload.get("items")
        normalized_items = _normalize_small_list(items)
        if normalized_items is None:
            await self.invalidate_small_list()
            return None
        return normalized_items

    async def set_small_list(
        self,
        items: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(
            build_small_list_cache_key(),
            {"items": items},
            ttl_seconds,
        )

    async def invalidate_small_list(self) -> None:
        await self.backend.delete(build_small_list_cache_key())

    async def get_small(self, key: str) -> dict[str, Any] | None:
        payload = await self.backend.get_json(build_small_cache_key(key))
        if payload is None:
            return None
        normalized_item = _normalize_small_item(payload, expected_key=key)
        if normalized_item is None:
            await self.invalidate_small(key)
            return None
        return normalized_item

    async def set_small(
        self,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(build_small_cache_key(key), payload, ttl_seconds)

    async def invalidate_small(self, key: str) -> None:
        await self.backend.delete(build_small_cache_key(key))

    async def invalidate_small_entry_and_list(self, key: str) -> None:
        await self._delete_keys((build_small_cache_key(key), build_small_list_cache_key()))

    async def get_large_list(self) -> list[dict[str, Any]] | None:
        payload = await self.backend.get_json(build_large_list_cache_key())
        if payload is None:
            return None
        if not isinstance(payload, dict):
            await self.invalidate_large_list()
            return None
        items = payload.get("items")
        normalized_items = _normalize_large_list(items)
        if normalized_items is None:
            await self.invalidate_large_list()
            return None
        return normalized_items

    async def set_large_list(
        self,
        items: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.backend.set_json(
            build_large_list_cache_key(),
            {"items": items},
            ttl_seconds,
        )

    async def invalidate_large_list(self) -> None:
        await self.backend.delete(build_large_list_cache_key())

    async def get_large(self, key1: str, key2: str) -> dict[str, Any] | None:
        payload = await self.backend.get_json(build_large_cache_key(key1, key2))
        if payload is None:
            return None
        normalized_item = _normalize_large_item(
            payload,
            expected_key1=key1,
            expected_key2=key2,
        )
        if normalized_item is None:
            await self.invalidate_large(key1, key2)
            return None
        return normalized_item

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

    async def invalidate_large_entry_and_list(self, key1: str, key2: str) -> None:
        await self._delete_keys((build_large_cache_key(key1, key2), build_large_list_cache_key()))


def get_request_i18n_cache_service(
    cache_service: RedisCacheService = Depends(get_request_cache_service),
) -> I18nCacheService:
    return I18nCacheService(backend=cache_service)
