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
_ROUTE_SCOPE_CACHE_ATTR = "_fastapi_rate_limit_route_scope_cache"


def _operability_logger():
    return get_logger("aranes.operability")


async def _rate_limit_callback(request: Request, response: Response) -> None:
    del request, response
    raise HTTPException(status_code=429, detail=_RATE_LIMIT_EXCEEDED_MESSAGE)


def _route_scope_cache(request: Request) -> dict[tuple[int, int, str], tuple[bool, str]]:
    cache = getattr(request.app.state, _ROUTE_SCOPE_CACHE_ATTR, None)
    if isinstance(cache, dict):
        return cache
    cache = {}
    setattr(request.app.state, _ROUTE_SCOPE_CACHE_ATTR, cache)
    return cache


def _resolve_route_scope(
    request: Request,
    dependency: FastAPIRateLimiter,
) -> tuple[bool, str]:
    route = request.scope.get("route")
    if route is not None:
        cache_key = (id(route), id(dependency), request.method)
        cache = _route_scope_cache(request)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        skip_limiter = bool(
            hasattr(route, "endpoint") and getattr(route.endpoint, "_skip_limiter", False)
        )
        dep_index = 0
        for index, route_dependency in enumerate(getattr(route, "dependencies", ()) or ()):
            if getattr(route_dependency, "dependency", None) is dependency:
                dep_index = index
                break
        route_path = (
            getattr(route, "path_format", None)
            or getattr(route, "path", None)
            or request.scope["path"]
        )
        resolved = (skip_limiter, f"{request.method}:{route_path}:{dep_index}")
        cache[cache_key] = resolved
        return resolved

    route_index = 0
    dep_index = 0
    skip_limiter = False
    for index, app_route in enumerate(request.app.routes):
        if (
            app_route.path == request.scope["path"]
            and hasattr(app_route, "methods")
            and request.method in app_route.methods
        ):
            route_index = index
            if hasattr(app_route, "endpoint") and getattr(app_route.endpoint, "_skip_limiter", False):
                skip_limiter = True
                break
            for dependency_index, route_dependency in enumerate(app_route.dependencies):
                if dependency is route_dependency.dependency:
                    dep_index = dependency_index
                    break
            break

    return skip_limiter, f"{route_index}:{dep_index}"


class _CachedFastAPIRateLimiter(FastAPIRateLimiter):
    async def __call__(self, request: Request, response: Response):
        skip_limiter, route_scope = _resolve_route_scope(request, self)
        if skip_limiter:
            return

        rate_key = await self.identifier(request)
        key = f"{rate_key}:{route_scope}"
        success = await self.limiter.try_acquire_async(key, blocking=self.blocking)
        if not success:
            return await self.callback(request, response)


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
            try:
                bootstrap_bucket = await RedisBucket.init(
                    [rate],
                    cache_service.client,
                    f"{_RATE_LIMIT_BUCKET_NAMESPACE}:bootstrap",
                )
            except Exception:
                cache_service.mark_unavailable()
                _operability_logger().warning("rate limiter redis bootstrap failed; using in-memory backend")
            else:
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
        runtime.cache_service.is_available(),
        id(runtime.cache_service.client),
    )


def _is_redis_backed_factory(factory: _KeyedBucketFactory) -> bool:
    return (
        factory.cache_service is not None
        and factory.cache_service.client is not None
        and factory.script_hash is not None
    )


async def _build_dependency_state(runtime: RuntimeContext) -> _RateLimitDependencyState:
    try:
        factory = await _KeyedBucketFactory.create_for_runtime(runtime)
    except Exception:
        runtime.cache_service.mark_unavailable()
        _operability_logger().warning("rate limiter falling back to in-memory backend")
        factory = _KeyedBucketFactory(
            rate=Rate(
                runtime.config.RATE_LIMIT_MAX_REQUESTS,
                Duration.SECOND * runtime.config.RATE_LIMIT_WINDOW_SECONDS,
            )
        )
    dependency = _CachedFastAPIRateLimiter(
        limiter=Limiter(factory),
        identifier=default_identifier,
        callback=_rate_limit_callback,
        blocking=False,
    )
    return _RateLimitDependencyState(
        runtime_signature=_runtime_signature(runtime),
        dependency=dependency,
        redis_backed=_is_redis_backed_factory(factory),
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
                _operability_logger().warning(
                    "rate limiter degraded; denying request",
                    request_id=getattr(request.state, "request_id", None),
                    path=request.url.path,
                    client_host=request.client.host if request.client is not None else "unknown",
                )
                raise HTTPException(status_code=429, detail=_RATE_LIMIT_EXCEEDED_MESSAGE)
            raise


request_rate_limiter = RequestRateLimiter()

__all__ = ["RequestRateLimiter", "request_rate_limiter"]
