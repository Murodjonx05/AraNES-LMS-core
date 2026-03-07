from src.utils.rate_limit import InMemoryRateLimiter


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
