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
    assert response.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_ready_is_open_and_reports_database_status(unauth_client: httpx.AsyncClient):
    response = await unauth_client.get("/ready")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "ok"
    assert payload["database_backend"] == "sqlite"


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
