from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from fastapi import HTTPException, Request, Response
from fastapi_limiter.depends import RateLimiter as FastAPIRateLimiter
from fastapi_limiter.identifier import default_identifier
from pyrate_limiter import (
    BucketAsyncWrapper,
    BucketFactory,
    Duration,
    InMemoryBucket,
    Limiter,
    Rate,
    RateItem,
    RedisBucket,
)

from src.runtime import RuntimeContext
from src.utils.cache import RedisCacheService
from src.utils.structured_logging import get_logger

_RATE_LIMIT_BUCKET_NAMESPACE = "rate_limit"
_RATE_LIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded"
_OPERABILITY_LOGGER = get_logger("aranes.operability")


async def _rate_limit_callback(request: Request, response: Response) -> None:
    del request, response
    raise HTTPException(status_code=429, detail=_RATE_LIMIT_EXCEEDED_MESSAGE)


@dataclass(slots=True)
class _KeyedBucketFactory(BucketFactory):
    rate: Rate
    cache_service: RedisCacheService | None = None
    script_hash: str | None = None
    _buckets: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @classmethod
    async def create_for_runtime(cls, runtime: RuntimeContext) -> "_KeyedBucketFactory":
        rate = Rate(
            runtime.config.RATE_LIMIT_MAX_REQUESTS,
            Duration.SECOND * runtime.config.RATE_LIMIT_WINDOW_SECONDS,
        )
        cache_service = runtime.cache_service
        if cache_service.enabled and cache_service.client is not None:
            bootstrap_bucket = await RedisBucket.init(
                [rate],
                cache_service.client,
                f"{_RATE_LIMIT_BUCKET_NAMESPACE}:bootstrap",
            )
            return cls(rate=rate, cache_service=cache_service, script_hash=bootstrap_bucket.script_hash)
        return cls(rate=rate)

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        return RateItem(name, time.time_ns() // 1_000_000, weight=weight)

    def get(self, item: RateItem):
        bucket = self._buckets.get(item.name)
        if bucket is not None:
            return bucket

        with self._lock:
            bucket = self._buckets.get(item.name)
            if bucket is not None:
                return bucket

            if self.cache_service is not None and self.cache_service.client is not None:
                if self.script_hash is None:
                    raise RuntimeError("Redis rate limiter is not initialized.")
                bucket = self.create(
                    RedisBucket,
                    [self.rate],
                    self.cache_service.client,
                    f"{_RATE_LIMIT_BUCKET_NAMESPACE}:{item.name}",
                    self.script_hash,
                )
            else:
                bucket = self.create(BucketAsyncWrapper, InMemoryBucket([self.rate]))

            self._buckets[item.name] = bucket
            return bucket


@dataclass(slots=True)
class _RateLimitDependencyState:
    runtime_signature: tuple[object, ...]
    dependency: FastAPIRateLimiter
    redis_backed: bool


def _runtime_signature(runtime: RuntimeContext) -> tuple[object, ...]:
    return (
        id(runtime),
        runtime.config.RATE_LIMIT_ENABLED,
        runtime.config.RATE_LIMIT_MAX_REQUESTS,
        runtime.config.RATE_LIMIT_WINDOW_SECONDS,
        runtime.cache_service.enabled,
        id(runtime.cache_service.client),
    )


async def _build_dependency_state(runtime: RuntimeContext) -> _RateLimitDependencyState:
    factory = await _KeyedBucketFactory.create_for_runtime(runtime)
    dependency = FastAPIRateLimiter(
        limiter=Limiter(factory),
        identifier=default_identifier,
        callback=_rate_limit_callback,
        blocking=False,
    )
    return _RateLimitDependencyState(
        runtime_signature=_runtime_signature(runtime),
        dependency=dependency,
        redis_backed=runtime.cache_service.enabled and runtime.cache_service.client is not None,
    )


class RequestRateLimiter:
    def __init__(self) -> None:
        self._state_attr = "_fastapi_rate_limit_dependency"

    async def __call__(self, request: Request, response: Response) -> None:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is None or not runtime.config.RATE_LIMIT_ENABLED:
            return

        state: _RateLimitDependencyState | None = getattr(request.app.state, self._state_attr, None)
        signature = _runtime_signature(runtime)
        if state is None or state.runtime_signature != signature:
            state = await _build_dependency_state(runtime)
            setattr(request.app.state, self._state_attr, state)

        try:
            await state.dependency(request, response)
        except HTTPException:
            raise
        except Exception:
            if state.redis_backed:
                runtime.cache_service.mark_unavailable()
                _OPERABILITY_LOGGER.warning(
                    "rate limiter degraded; denying request",
                    request_id=getattr(request.state, "request_id", None),
                    path=request.url.path,
                    client_host=request.client.host if request.client is not None else "unknown",
                )
                raise HTTPException(status_code=429, detail=_RATE_LIMIT_EXCEEDED_MESSAGE)
            raise


request_rate_limiter = RequestRateLimiter()

__all__ = ["RequestRateLimiter", "request_rate_limiter"]
