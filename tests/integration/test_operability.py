from __future__ import annotations

import json
import logging
import uuid

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_is_open_and_reports_ok(unauth_client: httpx.AsyncClient):
    response = await unauth_client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert response.json()["redis"] == {"enabled": False, "status": "disabled"}
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_ready_is_open_and_reports_database_status(unauth_client: httpx.AsyncClient):
    response = await unauth_client.get("/ready")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "ok"
    assert payload["database_backend"] == "sqlite"
    assert payload["redis"] == {"enabled": False, "status": "disabled"}
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_ready_hides_raw_database_exception_details(
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
):
    runtime = _get_runtime(client)
    caplog.set_level(logging.ERROR, logger="aranes.operability")

    class _BrokenConnection:
        async def __aenter__(self):
            raise RuntimeError("sqlite:///secret-db-path refused connection")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _BrokenEngine:
        def connect(self):
            return _BrokenConnection()

    original_engine = runtime.engine
    runtime.engine = _BrokenEngine()  # type: ignore[assignment]
    try:
        response = await client.get("/ready", headers={"X-Request-ID": "ready-failure-test"})
    finally:
        runtime.engine = original_engine

    assert response.status_code == 503, response.text
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["database"] == "error"
    assert payload["detail"] == "Database is unavailable."
    assert "secret-db-path" not in response.text
    assert response.headers.get("X-Request-ID") == "ready-failure-test"

    operability_records = [record for record in caplog.records if record.name == "aranes.operability"]
    assert operability_records


@pytest.mark.asyncio
async def test_unhandled_exceptions_return_request_id_header(client: httpx.AsyncClient):
    transport = getattr(client, "_transport", None)
    app = getattr(transport, "app", None)
    assert app is not None

    path = f"/boom-{uuid.uuid4().hex}"

    async def _boom():
        raise RuntimeError("boom")

    app.add_api_route(path, _boom, methods=["GET"])

    response = await client.get(path, headers={"X-Request-ID": "boom-test"})

    assert response.status_code == 500, response.text
    assert response.headers.get("X-Request-ID") == "boom-test"
    assert response.json() == {
        "detail": "Internal Server Error",
        "request_id": "boom-test",
    }


class _ToggleRedis:
    def __init__(self):
        self.alive = False

    async def ping(self):
        return self.alive

    async def aclose(self):
        return None


def _get_runtime(client: httpx.AsyncClient):
    transport = getattr(client, "_transport", None)
    app = getattr(transport, "app", None)
    assert app is not None
    runtime = getattr(app.state, "runtime", None)
    assert runtime is not None
    return runtime


@pytest.mark.asyncio
async def test_health_reports_redis_recovery_when_ping_starts_working(
    client: httpx.AsyncClient,
):
    runtime = _get_runtime(client)
    runtime.cache_service.enabled = True
    redis = _ToggleRedis()
    runtime.cache_service.client = redis
    runtime.cache_service._available = False

    first = await client.get("/health")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "degraded"
    assert first.json()["redis"] == {"enabled": True, "status": "unavailable", "available": False}

    redis.alive = True
    second = await client.get("/health")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "ok"
    assert second.json()["redis"] == {"enabled": True, "status": "ok", "available": True}
    assert runtime.cache_service.is_available() is True


@pytest.mark.asyncio
async def test_rate_limiter_denies_when_redis_fails_open(
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
):
    runtime = _get_runtime(client)
    transport = getattr(client, "_transport", None)
    app = getattr(transport, "app", None)
    assert app is not None
    caplog.set_level(logging.WARNING, logger="aranes.operability")

    class _BrokenRedis:
        async def incr(self, key: str) -> int:
            raise RuntimeError("redis offline")

        async def expire(self, key: str, ttl_seconds: int) -> None:
            return None

        async def aclose(self) -> None:
            return None

    limiter_cache_service = app.state.redis_rate_limiter.cache_service
    original_rate_limit_enabled = runtime.config.RATE_LIMIT_ENABLED
    original_runtime_enabled = runtime.cache_service.enabled
    original_enabled = limiter_cache_service.enabled
    original_client = limiter_cache_service.client
    runtime.config.RATE_LIMIT_ENABLED = True
    limiter_cache_service.enabled = True
    limiter_cache_service.client = _BrokenRedis()
    runtime.cache_service.enabled = True

    try:
        response = await client.post(
            "/api/v1/auth/login",
            headers={"X-Request-ID": "redis-down-test"},
            json={"username": "nobody", "password": "bad-password"},
        )
    finally:
        runtime.config.RATE_LIMIT_ENABLED = original_rate_limit_enabled
        runtime.cache_service.enabled = original_runtime_enabled
        limiter_cache_service.enabled = original_enabled
        limiter_cache_service.client = original_client

    assert response.status_code == 429, response.text
    assert response.headers.get("X-Request-ID") == "redis-down-test"
    assert response.json() == {"detail": "Rate limit exceeded"}
    assert any("rate limiter degraded; denying request" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_mutating_endpoint_emits_request_id_and_audit_log(
    client: httpx.AsyncClient,
    superuser_tokens: dict[str, str],
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO, logger="aranes.audit")
    response = await client.post(
        "/api/v1/rbac/users/reset",
        headers={"Authorization": f"Bearer {superuser_tokens['access']}"},
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("X-Request-ID")

    audit_records = [record for record in caplog.records if record.name == "aranes.audit"]
    assert audit_records
    payload = json.loads(audit_records[-1].getMessage())
    assert payload["event"] == "audit"
    assert payload["path"] == "/api/v1/rbac/users/reset"
    assert payload["status_code"] == 200


@pytest.mark.asyncio
async def test_invalid_bearer_token_is_logged_for_actor_extraction(
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.WARNING, logger="aranes.security")

    response = await client.post(
        "/api/v1/rbac/users/reset",
        headers={"Authorization": "Bearer definitely-not-a-jwt", "X-Request-ID": "bad-token-test"},
    )

    assert response.status_code == 401, response.text
    assert response.headers.get("X-Request-ID") == "bad-token-test"
    assert any("actor subject extraction failed" in record.getMessage() for record in caplog.records)
