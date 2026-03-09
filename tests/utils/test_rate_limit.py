from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from src.utils import rate_limit


class _FakeRedisClient:
    def __init__(self, *, fail_script_load: bool = False):
        self.loaded_scripts: list[str] = []
        self.fail_script_load = fail_script_load

    async def script_load(self, script: str) -> str:
        if self.fail_script_load:
            raise RuntimeError("redis bootstrap failed")
        self.loaded_scripts.append(script)
        return "script-hash"


class _FakeLimiter:
    def __init__(self):
        self.keys: list[str] = []

    async def try_acquire_async(self, key: str, blocking: bool = False):
        self.keys.append(f"{key}|blocking={blocking}")
        return True


async def _fake_identifier(request: Request) -> str:
    del request
    return "client-key"


class _CountingDependencies(list):
    def __init__(self, *args):
        super().__init__(*args)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def _build_runtime(*, redis_enabled: bool, client=None):
    cache_service = SimpleNamespace(
        enabled=redis_enabled,
        client=client,
        mark_unavailable=lambda: None,
        is_available=lambda: redis_enabled and client is not None,
    )
    config = SimpleNamespace(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_MAX_REQUESTS=2,
        RATE_LIMIT_WINDOW_SECONDS=60,
    )
    return SimpleNamespace(config=config, cache_service=cache_service)


@pytest.mark.asyncio
async def test_build_dependency_state_uses_in_memory_when_redis_disabled():
    runtime = _build_runtime(redis_enabled=False)

    state = await rate_limit._build_dependency_state(runtime)

    assert state.redis_backed is False


@pytest.mark.asyncio
async def test_build_dependency_state_initializes_redis_bucket_when_available():
    client = _FakeRedisClient()
    runtime = _build_runtime(redis_enabled=True, client=client)

    state = await rate_limit._build_dependency_state(runtime)

    assert state.redis_backed is True
    assert client.loaded_scripts


@pytest.mark.asyncio
async def test_build_dependency_state_marks_memory_fallback_as_not_redis_backed():
    marked = {"value": False}

    def _mark_unavailable():
        marked["value"] = True

    client = _FakeRedisClient(fail_script_load=True)
    runtime = _build_runtime(redis_enabled=True, client=client)
    runtime.cache_service.mark_unavailable = _mark_unavailable

    state = await rate_limit._build_dependency_state(runtime)

    assert state.redis_backed is False
    assert marked["value"] is True


@pytest.mark.asyncio
async def test_request_rate_limiter_denies_when_redis_backend_raises(monkeypatch: pytest.MonkeyPatch):
    marked = {"value": False}

    def _mark_unavailable():
        marked["value"] = True

    runtime = _build_runtime(redis_enabled=True, client=object())
    runtime.cache_service.mark_unavailable = _mark_unavailable

    class _BrokenDependency:
        async def __call__(self, request: Request, response: Response):
            del request, response
            raise RuntimeError("redis offline")

    async def _fake_build_dependency_state(_runtime):
        return rate_limit._RateLimitDependencyState(
            runtime_signature=rate_limit._runtime_signature(runtime),
            dependency=_BrokenDependency(),  # type: ignore[arg-type]
            redis_backed=True,
        )

    monkeypatch.setattr(rate_limit, "_build_dependency_state", _fake_build_dependency_state)

    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(runtime=runtime)),
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    request.state.request_id = "rate-limit-test"
    response = Response()

    with pytest.raises(HTTPException, match="Rate limit exceeded"):
        await rate_limit.RequestRateLimiter()(request, response)

    assert marked["value"] is True


@pytest.mark.asyncio
async def test_request_rate_limiter_does_not_fail_closed_for_in_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    marked = {"value": False}

    def _mark_unavailable():
        marked["value"] = True

    runtime = _build_runtime(redis_enabled=True, client=object())
    runtime.cache_service.mark_unavailable = _mark_unavailable

    class _BrokenDependency:
        async def __call__(self, request: Request, response: Response):
            del request, response
            raise RuntimeError("in-memory limiter bug")

    async def _fake_build_dependency_state(_runtime):
        return rate_limit._RateLimitDependencyState(
            runtime_signature=rate_limit._runtime_signature(runtime),
            dependency=_BrokenDependency(),  # type: ignore[arg-type]
            redis_backed=False,
        )

    monkeypatch.setattr(rate_limit, "_build_dependency_state", _fake_build_dependency_state)

    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(state=SimpleNamespace(runtime=runtime)),
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    request.state.request_id = "rate-limit-test"
    response = Response()

    with pytest.raises(RuntimeError, match="in-memory limiter bug"):
        await rate_limit.RequestRateLimiter()(request, response)

    assert marked["value"] is False


@pytest.mark.asyncio
async def test_cached_rate_limiter_reuses_route_scope_without_scanning_app_routes():
    limiter_backend = _FakeLimiter()
    dependency = rate_limit._CachedFastAPIRateLimiter(
        limiter=limiter_backend,  # type: ignore[arg-type]
        identifier=_fake_identifier,
        callback=rate_limit._rate_limit_callback,
        blocking=False,
    )
    dependencies = _CountingDependencies([SimpleNamespace(dependency=dependency)])
    route = SimpleNamespace(
        path="/api/v1/auth/login",
        path_format="/api/v1/auth/login",
        methods={"POST"},
        dependencies=dependencies,
        endpoint=SimpleNamespace(),
    )
    app = SimpleNamespace(state=SimpleNamespace())

    request_one = Request(
        {
            "type": "http",
            "app": app,
            "route": route,
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    request_two = Request(
        {
            "type": "http",
            "app": app,
            "route": route,
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    response = Response()

    await dependency(request_one, response)
    await dependency(request_two, response)

    assert dependencies.iterations == 1
    assert limiter_backend.keys == [
        "client-key:POST:/api/v1/auth/login:0|blocking=False",
        "client-key:POST:/api/v1/auth/login:0|blocking=False",
    ]


@pytest.mark.asyncio
async def test_cached_rate_limiter_falls_back_to_route_scan_when_scope_route_missing():
    limiter_backend = _FakeLimiter()
    dependency = rate_limit._CachedFastAPIRateLimiter(
        limiter=limiter_backend,  # type: ignore[arg-type]
        identifier=_fake_identifier,
        callback=rate_limit._rate_limit_callback,
        blocking=False,
    )
    route = SimpleNamespace(
        path="/api/v1/auth/login",
        methods={"POST"},
        dependencies=[SimpleNamespace(dependency=dependency)],
        endpoint=SimpleNamespace(),
    )
    app = SimpleNamespace(state=SimpleNamespace(), routes=[route])
    request = Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    response = Response()

    await dependency(request, response)

    assert limiter_backend.keys == ["client-key:0:0|blocking=False"]
