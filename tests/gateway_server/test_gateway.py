from __future__ import annotations

import logging
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from gateway_server.gateway import (
    ManagedServiceRuntime,
    allocate_free_port,
    create_app,
    discover_services,
    merge_openapi_documents,
)
from tests.conftest import DEMO_PLUGIN_OPENAPI, DEMO_PLUGIN_ROUTES


class _DeadProcess:
    def poll(self) -> int:
        return 1


@pytest.mark.asyncio
async def test_discover_services_returns_only_directories_with_run_script(tmp_path: Path):
    services_root = tmp_path / "services"
    (services_root / "alpha").mkdir(parents=True)
    (services_root / "alpha" / "run.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (services_root / "beta").mkdir()
    (services_root / "notes.txt").write_text("ignored", encoding="utf-8")

    discovered = discover_services(services_root)

    assert [service.name for service in discovered] == ["alpha"]
    assert discovered[0].run_script == services_root / "alpha" / "run.sh"


def test_allocate_free_port_skips_ports_that_are_already_bound():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        occupied_port = probe.getsockname()[1]
        port = allocate_free_port(occupied_port)

    assert port != occupied_port
    assert port > occupied_port


def test_merge_openapi_documents_namespaces_schemas_and_rewrites_refs():
    documents = {
        "demo_fastapi": {
            "openapi": "3.1.0",
            "paths": {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "items": {"$ref": "#/components/schemas/Item"},
                                            "type": "array",
                                        }
                                    }
                                },
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "Item": {
                        "properties": {
                            "owner": {"$ref": "#/components/schemas/Owner"},
                        },
                        "type": "object",
                    },
                    "Owner": {"properties": {"name": {"type": "string"}}, "type": "object"},
                }
            },
            "tags": [{"name": "demo"}],
        }
    }

    merged = merge_openapi_documents(documents)

    assert merged["components"]["schemas"]["demo_fastapi_Item"]["properties"]["owner"]["$ref"] == (
        "#/components/schemas/demo_fastapi_Owner"
    )
    schema_ref = merged["paths"]["/plg/demo_fastapi/items"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["items"]["$ref"]
    assert schema_ref == "#/components/schemas/demo_fastapi_Item"
    assert merged["tags"] == [{"name": "demo"}]


@pytest.mark.asyncio
async def test_proxy_returns_404_for_unknown_service(tmp_path: Path):
    app = create_app(services_root=tmp_path / "services", registry={})
    app.state.active_services = {}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/plg/missing/ping")

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown service: missing"


@pytest.mark.asyncio
async def test_gateway_exposes_health_and_ready_endpoints(tmp_path: Path):
    app = create_app(services_root=tmp_path / "services", registry={})
    app.state.active_services = {}
    app.state.services_root = tmp_path / "services"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health_response = await client.get("/health")
        ready_response = await client.get("/ready")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "service": "plugin-gateway"}
    assert ready_response.status_code == 503
    assert ready_response.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_proxy_returns_502_when_service_process_is_not_running(tmp_path: Path):
    registry = {
        "demo_fastapi": ManagedServiceRuntime(
            name="demo_fastapi",
            directory=tmp_path,
            run_script=tmp_path / "run.sh",
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=_DeadProcess(),  # type: ignore[arg-type]
        )
    }
    app = create_app(services_root=tmp_path / "services", registry=registry)
    app.state.active_services = registry
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/plg/demo_fastapi/ping")

    assert response.status_code == 502
    assert response.json()["detail"] == "Service is unavailable: demo_fastapi"


@pytest.mark.asyncio
async def test_gateway_lifespan_starts_demo_service_and_aggregates_openapi(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    mock_plugin_server_factory,
):
    _gw_logger = logging.getLogger("gateway_server")

    async def _mock_launch(*, services_root, registry, start_port, readiness_timeout):
        next_port = start_port
        for service in discover_services(services_root):
            port = allocate_free_port(next_port)
            next_port = port + 1
            _, proc = mock_plugin_server_factory(port)
            runtime = ManagedServiceRuntime(
                name=service.name,
                directory=service.directory,
                run_script=service.run_script,
                port=port,
                base_url=f"http://127.0.0.1:{port}",
                process=proc,
            )
            registry[service.name] = runtime
            _gw_logger.info("Starting service %s on http://127.0.0.1:%s", service.name, port)
            _gw_logger.info("Started service %s on http://127.0.0.1:%s (pid=%s)", service.name, port, proc.pid)

    monkeypatch.setattr("gateway_server.gateway.launch_services", _mock_launch)

    registry: dict[str, ManagedServiceRuntime] = {}
    app = create_app(registry=registry)
    transport = httpx.ASGITransport(app=app)
    caplog.set_level(logging.INFO, logger="gateway_server")

    async with app.router.lifespan_context(app):
        process = registry["demo_fastapi"].process
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            ping_response = await client.get("/plg/demo_fastapi/ping")
            items_response = await client.get("/plg/demo_fastapi/items")
            openapi_response = await client.get("/openapi.json")
            docs_response = await client.get("/docs")

        assert ping_response.status_code == 200
        assert ping_response.json() == {"status": "ok"}
        assert items_response.status_code == 200
        assert items_response.json() == [
            {"id": 1, "name": "alpha"},
            {"id": 2, "name": "beta"},
        ]
        assert openapi_response.status_code == 200
        openapi = openapi_response.json()
        assert "/plg/demo_fastapi/ping" in openapi["paths"]
        assert "demo_fastapi_Item" in openapi["components"]["schemas"]
        assert docs_response.status_code == 200
        assert "/openapi.json" in docs_response.text
        assert process.poll() is None

    assert process.poll() is not None
    assert not registry
    assert "Started service demo_fastapi on http://127.0.0.1:" in caplog.text
