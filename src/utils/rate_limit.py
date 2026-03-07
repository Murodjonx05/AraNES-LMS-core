from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

from src.utils.cache import RedisCacheService

_STALE_BUCKET_SWEEP_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class InMemoryRateLimiter:
    time_fn: Callable[[], float] = time.monotonic
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _buckets: dict[str, deque[float]] = field(default_factory=dict, init=False, repr=False)
    _last_stale_sweep_at: float = field(default=0.0, init=False, repr=False)

    def _sweep_stale_buckets(self, *, now: float, cutoff: float) -> None:
        if now - self._last_stale_sweep_at < _STALE_BUCKET_SWEEP_INTERVAL_SECONDS:
            return
        stale_keys = [
            key
            for key, bucket in self._buckets.items()
            if not bucket or bucket[-1] <= cutoff
        ]
        for key in stale_keys:
            self._buckets.pop(key, None)
        self._last_stale_sweep_at = now

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = self.time_fn()
        cutoff = now - float(window_seconds)
        with self._lock:
            self._sweep_stale_buckets(now=now, cutoff=cutoff)
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                self._buckets.pop(key, None)
                bucket = self._buckets.setdefault(key, deque())
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


@dataclass(slots=True)
class RedisRateLimiter:
    cache_service: RedisCacheService
    time_fn: Callable[[], float] = time.time

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> bool | None:
        client = self.cache_service.client
        if not self.cache_service.enabled or client is None:
            return None

        now = self.time_fn()
        window = max(int(window_seconds), 1)
        window_id = int(now // window)
        bucket_key = f"rate_limit:{key}:{window_id}"
        ttl_seconds = max(window - int(now % window), 1)

        try:
            count = await client.incr(bucket_key)
            if count == 1:
                await client.expire(bucket_key, ttl_seconds)
        except Exception:
            self.cache_service.mark_unavailable()
            return None
        return count <= limit
