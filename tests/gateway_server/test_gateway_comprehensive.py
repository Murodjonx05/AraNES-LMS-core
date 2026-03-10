"""Comprehensive tests for gateway_server covering all states and edge cases."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from gateway_server.gateway import (
    HOP_BY_HOP_HEADERS,
    DiscoveredService,
    ManagedServiceRuntime,
    PluginManifest,
    allocate_free_port,
    create_app,
    discover_services,
    fetch_service_openapi_documents,
    merge_openapi_documents,
    public_plugin_prefix,
    rewrite_schema_refs,
    shutdown_services,
    terminate_process,
    to_internal_plugin_path,
    to_public_openapi_paths,
    wait_for_service_ready,
)


# ============================================================================
# UNIT TESTS - Path Transformation
# ============================================================================


class TestPathTransformation:
    """Test path transformation functions for plugin routing."""

    def test_public_plugin_prefix_returns_correct_format(self):
        assert public_plugin_prefix("demo") == "/plg/demo"
        assert public_plugin_prefix("my_service") == "/plg/my_service"

    def test_to_internal_plugin_path_strips_prefix(self):
        assert to_internal_plugin_path("/plg/demo/items", "demo") == "/items"
        assert to_internal_plugin_path("/plg/demo/api/v1/users", "demo") == "/api/v1/users"

    def test_to_internal_plugin_path_handles_root(self):
        assert to_internal_plugin_path("/plg/demo", "demo") == "/"

    def test_to_internal_plugin_path_handles_no_leading_slash(self):
        assert to_internal_plugin_path("plg/demo/items", "demo") == "/items"

    def test_to_internal_plugin_path_preserves_unmatched_paths(self):
        assert to_internal_plugin_path("/other/path", "demo") == "/other/path"

    def test_to_public_openapi_paths_adds_prefix(self):
        paths = {
            "/items": {"get": {"summary": "List items"}},
            "/items/{id}": {"get": {"summary": "Get item"}},
        }
        result = to_public_openapi_paths(paths, "demo")
        assert "/plg/demo/items" in result
        assert "/plg/demo/items/{id}" in result

    def test_to_public_openapi_paths_handles_root(self):
        paths = {"/": {"get": {"summary": "Root"}}}
        result = to_public_openapi_paths(paths, "demo")
        assert "/plg/demo" in result

    def test_to_public_openapi_paths_handles_already_prefixed(self):
        paths = {"/plg/demo/items": {"get": {"summary": "Items"}}}
        result = to_public_openapi_paths(paths, "demo")
        assert "/plg/demo/items" in result


# ============================================================================
# UNIT TESTS - Schema Rewriting
# ============================================================================


class TestSchemaRewriting:
    """Test OpenAPI schema reference rewriting."""

    def test_rewrite_schema_refs_in_dict(self):
        schema = {
            "properties": {
                "owner": {"$ref": "#/components/schemas/Owner"}
            }
        }
        result = rewrite_schema_refs(schema, "demo")
        assert result["properties"]["owner"]["$ref"] == "#/components/schemas/demo_Owner"

    def test_rewrite_schema_refs_in_nested_dict(self):
        schema = {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {"properties": {"child": {"$ref": "#/components/schemas/Child"}}}
            ]
        }
        result = rewrite_schema_refs(schema, "svc")
        assert result["allOf"][0]["$ref"] == "#/components/schemas/svc_Base"
        assert result["allOf"][1]["properties"]["child"]["$ref"] == "#/components/schemas/svc_Child"

    def test_rewrite_schema_refs_in_list(self):
        schema = [
            {"$ref": "#/components/schemas/Item1"},
            {"$ref": "#/components/schemas/Item2"}
        ]
        result = rewrite_schema_refs(schema, "api")
        assert result[0]["$ref"] == "#/components/schemas/api_Item1"
        assert result[1]["$ref"] == "#/components/schemas/api_Item2"

    def test_rewrite_schema_refs_preserves_external_refs(self):
        schema = {"$ref": "https://example.com/schemas/External"}
        result = rewrite_schema_refs(schema, "demo")
        assert result["$ref"] == "https://example.com/schemas/External"

    def test_rewrite_schema_refs_preserves_primitives(self):
        schema = {"type": "string", "maxLength": 100}
        result = rewrite_schema_refs(schema, "demo")
        assert result == {"type": "string", "maxLength": 100}


# ============================================================================
# UNIT TESTS - OpenAPI Merging
# ============================================================================


class TestOpenAPIMerging:
    """Test OpenAPI document merging functionality."""

    def test_merge_empty_documents(self):
        result = merge_openapi_documents({})
        assert result["openapi"] == "3.1.0"
        assert result["paths"] == {}
        assert "components" not in result
        assert "tags" not in result

    def test_merge_single_service(self):
        documents = {
            "service1": {
                "openapi": "3.1.0",
                "paths": {"/health": {"get": {}}},
                "components": {"schemas": {"Item": {"type": "object"}}},
            }
        }
        result = merge_openapi_documents(documents)
        assert "/plg/service1/health" in result["paths"]
        assert "service1_Item" in result["components"]["schemas"]

    def test_merge_multiple_services(self):
        documents = {
            "svc1": {
                "paths": {"/items": {"get": {}}},
                "components": {"schemas": {"Item": {"type": "object"}}},
            },
            "svc2": {
                "paths": {"/users": {"get": {}}},
                "components": {"schemas": {"User": {"type": "object"}}},
            }
        }
        result = merge_openapi_documents(documents)
        assert "/plg/svc1/items" in result["paths"]
        assert "/plg/svc2/users" in result["paths"]
        assert "svc1_Item" in result["components"]["schemas"]
        assert "svc2_User" in result["components"]["schemas"]

    def test_merge_handles_duplicate_tags(self):
        documents = {
            "svc1": {"paths": {}, "tags": [{"name": "common"}]},
            "svc2": {"paths": {}, "tags": [{"name": "common"}]},
        }
        result = merge_openapi_documents(documents)
        assert len(result["tags"]) == 1
        assert result["tags"][0]["name"] == "common"

    def test_merge_preserves_tag_order(self):
        documents = {
            "svc1": {"paths": {}, "tags": [{"name": "alpha"}, {"name": "beta"}]},
            "svc2": {"paths": {}, "tags": [{"name": "gamma"}]},
        }
        result = merge_openapi_documents(documents)
        tag_names = [tag["name"] for tag in result["tags"]]
        assert tag_names == ["alpha", "beta", "gamma"]

    def test_merge_handles_no_components(self):
        documents = {
            "svc1": {"paths": {"/health": {"get": {}}}},
        }
        result = merge_openapi_documents(documents)
        assert "components" not in result


# ============================================================================
# UNIT TESTS - Service Discovery
# ============================================================================


class TestServiceDiscovery:
    """Test service discovery functionality."""

    def test_discover_services_empty_directory(self, tmp_path: Path):
        services_root = tmp_path / "services"
        services_root.mkdir()
        result = discover_services(services_root)
        assert result == []

    def test_discover_services_nonexistent_directory(self, tmp_path: Path):
        result = discover_services(tmp_path / "nonexistent")
        assert result == []

    def test_discover_services_with_manifest(self, tmp_path: Path):
        services_root = tmp_path / "services"
        service_dir = services_root / "demo"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        manifest = {
            "plugin_name": "demo_plugin",
            "version": "1.0.0",
            "runtime": "python",
            "start_command": ["python", "main.py"],
            "health_path": "/healthz",
            "openapi_path": "/openapi.json",
            "startup_timeout_seconds": 30.0,
            "auto_start": True,
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].name == "demo_plugin"
        assert result[0].manifest is not None
        assert result[0].manifest.version == "1.0.0"
        assert result[0].manifest.runtime == "python"

    def test_discover_services_without_manifest(self, tmp_path: Path):
        services_root = tmp_path / "services"
        service_dir = services_root / "simple"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].name == "simple"
        assert result[0].manifest is None

    def test_discover_services_ignores_files(self, tmp_path: Path):
        services_root = tmp_path / "services"
        services_root.mkdir()
        (services_root / "readme.txt").write_text("ignore me")
        (services_root / "config.json").write_text("{}")

        result = discover_services(services_root)
        assert result == []

    def test_discover_services_ignores_dirs_without_run_script(self, tmp_path: Path):
        services_root = tmp_path / "services"
        (services_root / "incomplete").mkdir(parents=True)
        (services_root / "incomplete" / "app.py").write_text("# no run.sh")

        result = discover_services(services_root)
        assert result == []

    def test_discover_services_sorts_by_name(self, tmp_path: Path):
        services_root = tmp_path / "services"
        for name in ["zulu", "alpha", "mike"]:
            service_dir = services_root / name
            service_dir.mkdir(parents=True)
            (service_dir / "run.sh").write_text("#!/bin/bash\n")

        result = discover_services(services_root)
        names = [s.name for s in result]
        assert names == ["alpha", "mike", "zulu"]

    def test_discover_services_handles_invalid_manifest(self, tmp_path: Path):
        services_root = tmp_path / "services"
        service_dir = services_root / "broken"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        (service_dir / "manifest.json").write_text("invalid json{{{")

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is None


# ============================================================================
# UNIT TESTS - Port Allocation
# ============================================================================


class TestPortAllocation:
    """Test port allocation functionality."""

    def test_allocate_free_port_returns_available_port(self):
        port = allocate_free_port(10000)
        assert port >= 10000

    def test_allocate_free_port_increments_on_occupied(self):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            occupied = sock.getsockname()[1]
            port = allocate_free_port(occupied)
            assert port > occupied

    def test_allocate_free_port_with_high_start_value(self):
        port = allocate_free_port(50000)
        assert port >= 50000


# ============================================================================
# UNIT TESTS - HOP_BY_HOP_HEADERS
# ============================================================================


class TestHopByHopHeaders:
    """Test HOP_BY_HOP_HEADERS constant."""

    def test_hop_by_hop_headers_is_frozenset(self):
        assert isinstance(HOP_BY_HOP_HEADERS, frozenset)

    def test_hop_by_hop_headers_contains_required_headers(self):
        required = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }
        assert required.issubset(HOP_BY_HOP_HEADERS)

    def test_hop_by_hop_headers_immutable(self):
        with pytest.raises(AttributeError):
            HOP_BY_HOP_HEADERS.add("new-header")  # type: ignore


# ============================================================================
# INTEGRATION TESTS - Process Lifecycle
# ============================================================================


class TestProcessLifecycle:
    """Test process lifecycle management."""

    @pytest.mark.asyncio
    async def test_terminate_process_on_already_dead_process(self):
        mock_process = Mock()
        mock_process.poll.return_value = 1  # Already dead
        mock_process.terminate = Mock()

        await terminate_process(mock_process)
        mock_process.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminate_process_graceful_shutdown(self):
        mock_process = Mock()
        mock_process.poll.side_effect = [None, 0]  # Running, then stopped
        mock_process.terminate = Mock()
        mock_process.wait = Mock()

        await terminate_process(mock_process)
        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_services_clears_registry(self):
        mock_process1 = Mock()
        mock_process1.poll.return_value = 1
        mock_process2 = Mock()
        mock_process2.poll.return_value = 1

        registry = {
            "svc1": ManagedServiceRuntime(
                name="svc1",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process1,
            ),
            "svc2": ManagedServiceRuntime(
                name="svc2",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10002,
                base_url="http://127.0.0.1:10002",
                process=mock_process2,
            ),
        }

        await shutdown_services(registry)
        assert len(registry) == 0


# ============================================================================
# INTEGRATION TESTS - Service Readiness
# ============================================================================


class TestServiceReadiness:
    """Test service readiness checking."""

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_success(self):
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await wait_for_service_ready(
                process=mock_process,
                base_url="http://127.0.0.1:10000",
                timeout_seconds=5.0,
            )

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_process_exits(self):
        mock_process = Mock()
        mock_process.poll.return_value = 1  # Exited

        with pytest.raises(RuntimeError, match="Service process exited"):
            await wait_for_service_ready(
                process=mock_process,
                base_url="http://127.0.0.1:10000",
                timeout_seconds=1.0,
            )

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_timeout(self):
        mock_process = Mock()
        mock_process.poll.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            with pytest.raises(TimeoutError, match="did not become ready"):
                await wait_for_service_ready(
                    process=mock_process,
                    base_url="http://127.0.0.1:10000",
                    timeout_seconds=0.1,
                )


# ============================================================================
# INTEGRATION TESTS - OpenAPI Fetching
# ============================================================================


class TestOpenAPIFetching:
    """Test OpenAPI document fetching."""

    @pytest.mark.asyncio
    async def test_fetch_service_openapi_documents_success(self):
        mock_process = Mock()
        mock_process.poll.return_value = None  # Running

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        openapi_doc = {"openapi": "3.1.0", "paths": {}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = openapi_doc
            mock_response.raise_for_status = Mock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await fetch_service_openapi_documents(registry)
            assert "demo" in result
            assert result["demo"] == openapi_doc

    @pytest.mark.asyncio
    async def test_fetch_service_openapi_documents_uses_manifest_openapi_path(self):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
                manifest=PluginManifest(
                    plugin_name="demo",
                    version="1.0.0",
                    runtime="python",
                    start_command=[],
                    health_path="/healthz",
                    openapi_path="/schema.json",
                    startup_timeout_seconds=10.0,
                    auto_start=True,
                ),
            )
        }

        openapi_doc = {"openapi": "3.1.0", "paths": {}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = openapi_doc
            mock_response.raise_for_status = Mock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await fetch_service_openapi_documents(registry)

        assert result["demo"] == openapi_doc
        mock_client.get.assert_awaited_once_with("http://127.0.0.1:10001/schema.json")

    @pytest.mark.asyncio
    async def test_fetch_service_openapi_documents_skips_when_manifest_disables_openapi(self):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
                manifest=PluginManifest(
                    plugin_name="demo",
                    version="1.0.0",
                    runtime="python",
                    start_command=[],
                    health_path="/healthz",
                    openapi_path=None,
                    startup_timeout_seconds=10.0,
                    auto_start=True,
                ),
            )
        }

        result = await fetch_service_openapi_documents(registry)

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_service_openapi_documents_process_dead(self):
        mock_process = Mock()
        mock_process.poll.return_value = 1  # Dead

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        result = await fetch_service_openapi_documents(registry)
        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_service_openapi_documents_http_error(self):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.HTTPError("Connection failed")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await fetch_service_openapi_documents(registry)
            assert result == {}


# ============================================================================
# INTEGRATION TESTS - Gateway App
# ============================================================================


class TestGatewayApp:
    """Test gateway FastAPI application."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, tmp_path: Path):
        app = create_app(services_root=tmp_path, registry={})
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "plugin-gateway"}

    @pytest.mark.asyncio
    async def test_ready_endpoint_when_services_root_exists(self, tmp_path: Path):
        services_root = tmp_path / "services"
        services_root.mkdir()
        app = create_app(services_root=services_root, registry={})
        app.state.services_root = services_root
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    @pytest.mark.asyncio
    async def test_services_list_endpoint(self, tmp_path: Path):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=tmp_path,
                run_script=tmp_path / "run.sh",
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        app = create_app(services_root=tmp_path, registry=registry)
        app.state.active_services = registry
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/services")

        assert response.status_code == 200
        data = response.json()
        assert len(data["services"]) == 1
        assert data["services"][0]["name"] == "demo"
        assert data["services"][0]["status"] == "running"
        assert data["services"][0]["mount_prefix"] == "/plg/demo"

    @pytest.mark.asyncio
    async def test_proxy_with_query_params(self, tmp_path: Path):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=tmp_path,
                run_script=tmp_path / "run.sh",
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        app = create_app(services_root=tmp_path, registry=registry)
        app.state.active_services = registry

        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        
        async def mock_aiter_raw():
            yield b'{"result": "ok"}'
        
        mock_response.aiter_raw = mock_aiter_raw
        mock_response.aclose = AsyncMock()

        async def mock_send(request, **kwargs):
            return mock_response

        mock_client.build_request = Mock(return_value=Mock())
        mock_client.send = mock_send
        app.state.proxy_http_client = mock_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/plg/demo/items?page=1&limit=10")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_proxy_handles_exact_plugin_prefix(self, tmp_path: Path):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=tmp_path,
                run_script=tmp_path / "run.sh",
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        app = create_app(services_root=tmp_path, registry=registry)
        app.state.active_services = registry

        captured_url: dict[str, str] = {}
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        async def mock_aiter_raw():
            yield b'{"result": "ok"}'

        mock_response.aiter_raw = mock_aiter_raw
        mock_response.aclose = AsyncMock()

        def mock_build_request(method, url, **kwargs):
            return httpx.Request(method, url, **kwargs)

        async def mock_send(request, **kwargs):
            captured_url["value"] = str(request.url)
            return mock_response

        mock_client.build_request = Mock(side_effect=mock_build_request)
        mock_client.send = mock_send
        app.state.proxy_http_client = mock_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/plg/demo")

        assert response.status_code == 200
        assert captured_url["value"] == "http://127.0.0.1:10001/"

    @pytest.mark.asyncio
    async def test_proxy_filters_hop_by_hop_headers(self, tmp_path: Path):
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=tmp_path,
                run_script=tmp_path / "run.sh",
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        app = create_app(services_root=tmp_path, registry=registry)
        app.state.active_services = registry

        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-type": "application/json",
            "connection": "keep-alive",  # Should be filtered
            "transfer-encoding": "chunked",  # Should be filtered
            "x-custom": "value",  # Should be kept
        }
        
        async def mock_aiter_raw():
            yield b'{}'
        
        mock_response.aiter_raw = mock_aiter_raw
        mock_response.aclose = AsyncMock()

        async def mock_send(request, **kwargs):
            return mock_response

        mock_client.build_request = Mock(return_value=Mock())
        mock_client.send = mock_send
        app.state.proxy_http_client = mock_client

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/plg/demo/test")

        assert response.status_code == 200
        assert "connection" not in response.headers
        assert "transfer-encoding" not in response.headers
        assert response.headers.get("x-custom") == "value"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_merge_openapi_with_conflicting_paths(self, caplog):
        documents = {
            "svc1": {"paths": {"/items": {"get": {"summary": "Service 1"}}}},
            "svc2": {"paths": {"/items": {"get": {"summary": "Service 2"}}}},
        }
        result = merge_openapi_documents(documents)
        # Both should be present with different prefixes
        assert "/plg/svc1/items" in result["paths"]
        assert "/plg/svc2/items" in result["paths"]

    def test_discover_services_with_manifest_missing_fields(self, tmp_path: Path):
        services_root = tmp_path / "services"
        service_dir = services_root / "minimal"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        (service_dir / "manifest.json").write_text(json.dumps({}))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.plugin_name == "minimal"
        assert result[0].manifest.version == "0.0.0"
        assert result[0].manifest.runtime == "unknown"

    def test_to_public_openapi_paths_with_empty_paths(self):
        result = to_public_openapi_paths({}, "demo")
        assert result == {}

    def test_rewrite_schema_refs_with_none_values(self):
        schema = {"property": None}
        result = rewrite_schema_refs(schema, "demo")
        assert result["property"] is None

    @pytest.mark.asyncio
    async def test_proxy_with_all_http_methods(self, tmp_path: Path):
        """Test that proxy supports all HTTP methods."""
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry = {
            "demo": ManagedServiceRuntime(
                name="demo",
                directory=tmp_path,
                run_script=tmp_path / "run.sh",
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        app = create_app(services_root=tmp_path, registry=registry)
        app.state.active_services = registry

        for method in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {}
            
            async def mock_aiter_raw():
                yield b'{}'
            
            mock_response.aiter_raw = mock_aiter_raw
            mock_response.aclose = AsyncMock()

            async def mock_send(request, **kwargs):
                return mock_response

            mock_client.build_request = Mock(return_value=Mock())
            mock_client.send = mock_send
            app.state.proxy_http_client = mock_client

            transport = httpx.ASGITransport(app=app)

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.request(method, "/plg/demo/test")
                assert response.status_code == 200
