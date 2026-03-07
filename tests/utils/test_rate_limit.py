import pytest

from src.utils.rate_limit import InMemoryRateLimiter
from src.utils.rate_limit import RedisRateLimiter


class _FakeRedisClient:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.expiry: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        value = self.counts.get(key, 0) + 1
        self.counts[key] = value
        return value

    async def expire(self, key: str, ttl_seconds: int) -> None:
        self.expiry[key] = ttl_seconds


class _FakeCacheService:
    def __init__(self, *, enabled: bool = True, client=None):
        self.enabled = enabled
        self.client = client
        self.marked_unavailable = False

    def mark_unavailable(self) -> None:
        self.marked_unavailable = True


def test_rate_limiter_blocks_after_limit_within_window():
    clock = iter([0.0, 1.0, 2.0])
    limiter = InMemoryRateLimiter(time_fn=lambda: next(clock))

    assert limiter.allow("key", limit=2, window_seconds=60) is True
    assert limiter.allow("key", limit=2, window_seconds=60) is True
    assert limiter.allow("key", limit=2, window_seconds=60) is False


def test_rate_limiter_allows_again_after_window_expires():
    clock = iter([0.0, 1.0, 65.0])
    limiter = InMemoryRateLimiter(time_fn=lambda: next(clock))

    assert limiter.allow("key", limit=2, window_seconds=60) is True
    assert limiter.allow("key", limit=2, window_seconds=60) is True
    assert limiter.allow("key", limit=2, window_seconds=60) is True


def test_rate_limiter_sweeps_stale_keys():
    clock = iter([0.0, 61.0, 61.0])
    limiter = InMemoryRateLimiter(time_fn=lambda: next(clock))

    assert limiter.allow("stale", limit=1, window_seconds=60) is True
    assert "stale" in limiter._buckets
    assert limiter.allow("fresh", limit=1, window_seconds=60) is True

    assert "stale" not in limiter._buckets
    assert "fresh" in limiter._buckets


@pytest.mark.asyncio
async def test_redis_rate_limiter_blocks_after_limit_within_window():
    cache_service = _FakeCacheService(client=_FakeRedisClient())
    limiter = RedisRateLimiter(cache_service=cache_service, time_fn=lambda: 125.0)

    assert await limiter.allow("key", limit=2, window_seconds=60) is True
    assert await limiter.allow("key", limit=2, window_seconds=60) is True
    assert await limiter.allow("key", limit=2, window_seconds=60) is False
    assert cache_service.client.expiry["rate_limit:key:2"] == 55


@pytest.mark.asyncio
async def test_redis_rate_limiter_returns_none_when_cache_disabled():
    cache_service = _FakeCacheService(enabled=False, client=_FakeRedisClient())
    limiter = RedisRateLimiter(cache_service=cache_service)

    assert await limiter.allow("key", limit=2, window_seconds=60) is None
