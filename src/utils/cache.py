from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - dependency/import guard
    Redis = None  # type: ignore[assignment]

_CACHE_LOGGER = logging.getLogger("aranes.cache")


def resolve_heartbeat_delay(schedule: tuple[int, ...], failure_count: int) -> int:
    if not schedule:
        return 43200
    index = min(max(failure_count - 1, 0), len(schedule) - 1)
    return int(schedule[index])


def get_request_cache_service(request: Request):
    if (runtime := getattr(request.app.state, "runtime", None)) is not None:
        return runtime.cache_service

    from src.runtime import get_default_runtime

    # Legacy fallback when request has no app.state.runtime (e.g. standalone scripts).
    return get_default_runtime().cache_service


@dataclass(slots=True)
class RedisCacheService:
    enabled: bool
    redis_url: str
    default_ttl_seconds: int
    heartbeat_enabled: bool
    heartbeat_schedule_seconds: tuple[int, ...]
    client: Redis | None = field(init=False, default=None)
    _available: bool = field(init=False, default=False)
    _heartbeat_task: asyncio.Task | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        if Redis is None:
            _CACHE_LOGGER.warning("redis_client_unavailable", reason="redis_package_missing")
            self.enabled = False
            return
        try:
            self.client = Redis.from_url(self.redis_url, decode_responses=True)
        except Exception:
            _CACHE_LOGGER.warning("redis_client_unavailable", redis_url=self.redis_url)
            self.enabled = False
            self.client = None

    def is_available(self) -> bool:
        return self.enabled and self._available and self.client is not None

    def mark_unavailable(self) -> None:
        self._available = False

    async def ping(self) -> bool:
        if not self.enabled or self.client is None:
            self._available = False
            return False
        try:
            pong = await self.client.ping()
        except Exception:
            self._available = False
            return False
        self._available = bool(pong)
        return self._available

    async def get_json(self, cache_key: str) -> dict[str, Any] | None:
        if not self.enabled or self.client is None:
            return None
        try:
            raw = await self.client.get(cache_key)
        except Exception:
            self.mark_unavailable()
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            try:
                await self.client.delete(cache_key)
            except Exception:
                self.mark_unavailable()
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    async def set_json(
        self,
        cache_key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            await self.client.set(
                cache_key,
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                ex=ttl_seconds or self.default_ttl_seconds,
            )
        except Exception:
            self.mark_unavailable()

    async def delete(self, cache_key: str) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            await self.client.delete(cache_key)
        except Exception:
            self.mark_unavailable()

    async def delete_many(self, cache_keys: list[str]) -> None:
        if not cache_keys or not self.enabled or self.client is None:
            return
        try:
            await self.client.delete(*cache_keys)
        except Exception:
            self.mark_unavailable()

    async def start_heartbeat(self) -> None:
        await self.start_heartbeat_with_delay()

    async def start_heartbeat_with_delay(self, *, initial_delay_seconds: float = 0) -> None:
        if not self.enabled or not self.heartbeat_enabled or self.client is None:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(
            self.heartbeat_loop(initial_delay_seconds=initial_delay_seconds)
        )

    async def heartbeat_loop(self, *, initial_delay_seconds: float = 0) -> None:
        schedule = self.heartbeat_schedule_seconds or (43200,)
        failure_count = 0
        if initial_delay_seconds > 0:
            await asyncio.sleep(initial_delay_seconds)
        while True:
            ok = await self.ping()
            if ok:
                failure_count = 0
            else:
                failure_count += 1
                _CACHE_LOGGER.warning(
                    "redis_unavailable",
                    extra={
                        "redis_url": self.redis_url,
                        "next_retry_seconds": resolve_heartbeat_delay(schedule, failure_count),
                    },
                )
            await asyncio.sleep(resolve_heartbeat_delay(schedule, failure_count))

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self.client is not None:
            client = self.client
            self.client = None
            self._available = False
            await client.aclose()
        else:
            self._available = False
