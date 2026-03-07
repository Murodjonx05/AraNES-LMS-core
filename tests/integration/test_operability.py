from __future__ import annotations

import json
import logging

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

    operability_records = [record for record in caplog.records if record.name == "aranes.operability"]
    assert operability_records


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
