from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from src.utils import rate_limit


class _FakeRedisClient:
    def __init__(self):
        self.loaded_scripts: list[str] = []

    async def script_load(self, script: str) -> str:
        self.loaded_scripts.append(script)
        return "script-hash"


def _build_runtime(*, redis_enabled: bool, client=None):
    cache_service = SimpleNamespace(enabled=redis_enabled, client=client, mark_unavailable=lambda: None)
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
