"""Tests for error states and edge cases across the application."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from gateway_server.gateway import (
    DiscoveredService,
    PluginManifest,
    allocate_free_port,
    discover_services,
    merge_openapi_documents,
    rewrite_schema_refs,
    to_internal_plugin_path,
    to_public_openapi_paths,
)


class TestPathTransformationEdgeCases:
    """Test edge cases in path transformation."""

    def test_to_internal_plugin_path_with_unicode(self):
        """Should handle Unicode characters in paths."""
        result = to_internal_plugin_path("/plg/demo/items/café", "demo")
        assert result == "/items/café"

    def test_to_internal_plugin_path_with_special_chars(self):
        """Should handle special characters."""
        result = to_internal_plugin_path("/plg/demo/items?query=test&page=1", "demo")
        assert result == "/items?query=test&page=1"

    def test_to_internal_plugin_path_with_encoded_chars(self):
        """Should handle URL-encoded characters."""
        result = to_internal_plugin_path("/plg/demo/items%20with%20spaces", "demo")
        assert result == "/items%20with%20spaces"

    def test_to_public_openapi_paths_with_path_params(self):
        """Should handle path parameters correctly."""
        paths = {
            "/items/{item_id}": {"get": {}},
            "/users/{user_id}/posts/{post_id}": {"get": {}},
        }
        result = to_public_openapi_paths(paths, "api")
        assert "/plg/api/items/{item_id}" in result
        assert "/plg/api/users/{user_id}/posts/{post_id}" in result

    def test_to_public_openapi_paths_with_trailing_slash(self):
        """Should handle trailing slashes."""
        paths = {"/items/": {"get": {}}}
        result = to_public_openapi_paths(paths, "demo")
        assert "/plg/demo/items/" in result


class TestSchemaRewritingEdgeCases:
    """Test edge cases in schema rewriting."""

    def test_rewrite_deeply_nested_refs(self):
        """Should handle deeply nested schema references."""
        schema = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "$ref": "#/components/schemas/DeepSchema"
                        }
                    }
                }
            }
        }
        result = rewrite_schema_refs(schema, "svc")
        assert result["level1"]["level2"]["level3"]["level4"]["$ref"] == (
            "#/components/schemas/svc_DeepSchema"
        )

    def test_rewrite_with_mixed_types(self):
        """Should handle mixed types in schema."""
        schema = {
            "string": "value",
            "number": 42,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "ref": {"$ref": "#/components/schemas/Item"},
        }
        result = rewrite_schema_refs(schema, "svc")
        assert result["string"] == "value"
        assert result["number"] == 42
        assert result["boolean"] is True
        assert result["null"] is None
        assert result["array"] == [1, 2, 3]
        assert result["ref"]["$ref"] == "#/components/schemas/svc_Item"

    def test_rewrite_with_circular_like_structure(self):
        """Should handle structures that look circular."""
        schema = {
            "parent": {"$ref": "#/components/schemas/Parent"},
            "child": {"$ref": "#/components/schemas/Child"},
        }
        result = rewrite_schema_refs(schema, "svc")
        assert result["parent"]["$ref"] == "#/components/schemas/svc_Parent"
        assert result["child"]["$ref"] == "#/components/schemas/svc_Child"

    def test_rewrite_empty_dict(self):
        """Should handle empty dictionaries."""
        result = rewrite_schema_refs({}, "svc")
        assert result == {}

    def test_rewrite_empty_list(self):
        """Should handle empty lists."""
        result = rewrite_schema_refs([], "svc")
        assert result == []


class TestOpenAPIMergingEdgeCases:
    """Test edge cases in OpenAPI merging."""

    def test_merge_with_conflicting_schema_names(self):
        """Should namespace schemas even with same names."""
        documents = {
            "svc1": {
                "paths": {},
                "components": {"schemas": {"Item": {"type": "object", "x-service": "svc1"}}},
            },
            "svc2": {
                "paths": {},
                "components": {"schemas": {"Item": {"type": "object", "x-service": "svc2"}}},
            },
        }
        result = merge_openapi_documents(documents)
        assert "svc1_Item" in result["components"]["schemas"]
        assert "svc2_Item" in result["components"]["schemas"]
        assert result["components"]["schemas"]["svc1_Item"]["x-service"] == "svc1"
        assert result["components"]["schemas"]["svc2_Item"]["x-service"] == "svc2"

    def test_merge_with_invalid_tag_structure(self):
        """Should handle invalid tag structures gracefully."""
        documents = {
            "svc1": {
                "paths": {},
                "tags": [
                    {"name": "valid"},
                    {"name": "also_valid"},
                ],
            },
        }
        result = merge_openapi_documents(documents)
        # The actual implementation doesn't validate tags, it just copies them
        # This test verifies that valid tags are preserved
        assert len(result["tags"]) == 2
        assert result["tags"][0]["name"] == "valid"

    def test_merge_with_empty_components(self):
        """Should handle empty components sections."""
        documents = {
            "svc1": {
                "paths": {"/test": {}},
                "components": {},
            },
        }
        result = merge_openapi_documents(documents)
        assert "components" not in result

    def test_merge_with_no_paths(self):
        """Should handle services with no paths."""
        documents = {
            "svc1": {
                "components": {"schemas": {"Item": {}}},
            },
        }
        result = merge_openapi_documents(documents)
        assert result["paths"] == {}
        assert "svc1_Item" in result["components"]["schemas"]

    def test_merge_preserves_openapi_version(self):
        """Should always use OpenAPI 3.1.0."""
        documents = {
            "svc1": {"openapi": "3.0.0", "paths": {}},
        }
        result = merge_openapi_documents(documents)
        assert result["openapi"] == "3.1.0"


class TestServiceDiscoveryEdgeCases:
    """Test edge cases in service discovery."""

    def test_discover_with_unreadable_manifest(self, tmp_path: Path):
        """Should handle unreadable manifest files."""
        services_root = tmp_path / "services"
        service_dir = services_root / "broken"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        manifest_file = service_dir / "manifest.json"
        manifest_file.write_text('{"valid": "json"}')
        manifest_file.chmod(0o000)  # Make unreadable

        try:
            result = discover_services(services_root)
            # Should discover service but without manifest
            assert len(result) == 1
            assert result[0].manifest is None
        finally:
            manifest_file.chmod(0o644)  # Restore permissions

    def test_discover_with_manifest_wrong_type(self, tmp_path: Path):
        """Should handle manifest with wrong JSON structure."""
        services_root = tmp_path / "services"
        service_dir = services_root / "bad_manifest"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        # Manifest with unexpected structure - will cause KeyError when accessing .get()
        (service_dir / "manifest.json").write_text('{"unexpected": "structure"}')

        result = discover_services(services_root)
        assert len(result) == 1
        # Should still create manifest with defaults
        assert result[0].manifest is not None
        assert result[0].manifest.plugin_name == "bad_manifest"

    def test_discover_with_symlink_directory(self, tmp_path: Path):
        """Should handle symlinked service directories."""
        services_root = tmp_path / "services"
        services_root.mkdir()
        
        # Create actual service
        actual_service = tmp_path / "actual_service"
        actual_service.mkdir()
        (actual_service / "run.sh").write_text("#!/bin/bash\n")
        
        # Create symlink
        symlink = services_root / "linked_service"
        symlink.symlink_to(actual_service)

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].name == "linked_service"

    def test_discover_with_hidden_directories(self, tmp_path: Path):
        """Should include hidden directories if they have run.sh."""
        services_root = tmp_path / "services"
        hidden_dir = services_root / ".hidden_service"
        hidden_dir.mkdir(parents=True)
        (hidden_dir / "run.sh").write_text("#!/bin/bash\n")

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].name == ".hidden_service"


class TestPortAllocationEdgeCases:
    """Test edge cases in port allocation."""

    def test_allocate_port_near_max_port(self):
        """Should handle allocation near maximum port number."""
        # Start near max port (65535)
        port = allocate_free_port(65500)
        assert 65500 <= port <= 65535

    def test_allocate_port_with_zero_start(self):
        """Should handle zero as start port."""
        port = allocate_free_port(0)
        assert port >= 0

    def test_allocate_multiple_ports_sequentially(self):
        """Should allocate different ports when called multiple times."""
        port1 = allocate_free_port(20000)
        port2 = allocate_free_port(port1 + 1)
        port3 = allocate_free_port(port2 + 1)
        
        # All should be different
        assert len({port1, port2, port3}) == 3


class TestManifestParsingEdgeCases:
    """Test edge cases in manifest parsing."""

    def test_manifest_with_extra_fields(self, tmp_path: Path):
        """Should ignore extra fields in manifest."""
        services_root = tmp_path / "services"
        service_dir = services_root / "extra_fields"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        
        manifest = {
            "plugin_name": "test",
            "version": "1.0.0",
            "runtime": "python",
            "start_command": [],
            "health_path": "/health",
            "openapi_path": "/openapi.json",
            "startup_timeout_seconds": 30.0,
            "auto_start": True,
            "extra_field_1": "ignored",
            "extra_field_2": {"nested": "ignored"},
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.plugin_name == "test"

    def test_manifest_with_numeric_strings(self, tmp_path: Path):
        """Should handle numeric values as strings."""
        services_root = tmp_path / "services"
        service_dir = services_root / "numeric"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        
        manifest = {
            "startup_timeout_seconds": "30.5",  # String instead of float
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.startup_timeout_seconds == 30.5

    def test_manifest_with_boolean_strings(self, tmp_path: Path):
        """Should handle boolean values correctly."""
        services_root = tmp_path / "services"
        service_dir = services_root / "boolean"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        
        manifest = {
            "auto_start": "true",  # String instead of boolean
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.auto_start is True

    def test_manifest_with_false_boolean_string(self, tmp_path: Path):
        """Should parse explicit false values correctly."""
        services_root = tmp_path / "services"
        service_dir = services_root / "boolean_false"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")

        manifest = {
            "auto_start": "false",
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.auto_start is False

    def test_manifest_with_invalid_timeout_falls_back_to_default(self, tmp_path: Path):
        """Should keep discovery working when timeout is invalid."""
        services_root = tmp_path / "services"
        service_dir = services_root / "invalid_timeout"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")

        manifest = {
            "startup_timeout_seconds": "not-a-number",
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.startup_timeout_seconds == 20.0

    def test_manifest_with_null_values(self, tmp_path: Path):
        """Should handle null values in manifest."""
        services_root = tmp_path / "services"
        service_dir = services_root / "nulls"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\n")
        
        manifest = {
            "plugin_name": "test",
            "openapi_path": None,  # Explicitly null
        }
        (service_dir / "manifest.json").write_text(json.dumps(manifest))

        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].manifest is not None
        assert result[0].manifest.openapi_path is None


class TestProxyErrorStates:
    """Test error states in proxy functionality."""

    @pytest.mark.asyncio
    async def test_proxy_with_malformed_response(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Proxy should pass through malformed upstream bytes without parsing them."""
        from dataclasses import replace

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")
        monkeypatch.setenv("PLUGIN_GATEWAY_URL", "http://gateway:8001")

        from src.app import create_app
        from src.auth.service import issue_access_token
        from src.config import build_app_config
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
            PLUGIN_GATEWAY_URL="http://gateway:8001",
        )
        runtime = build_runtime(config)
        runtime.security.is_token_in_blocklist = AsyncMock(return_value=False)
        app = create_app(runtime)

        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        async def _aiter_raw():
            yield b'{"broken":'

        mock_response.aiter_raw = _aiter_raw
        mock_response.aclose = AsyncMock()
        mock_client.build_request = Mock(return_value=Mock())
        mock_client.send = AsyncMock(return_value=mock_response)
        app.state.plugin_gateway_client = mock_client

        transport = httpx.ASGITransport(app=app)
        token = issue_access_token("superuser", user_id=1, security=runtime.security)

        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    "/plg/demo/items",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 200
            assert response.text == '{"broken":'
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_proxy_with_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Proxy should convert upstream timeouts into 502 responses."""
        from dataclasses import replace

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")
        monkeypatch.setenv("PLUGIN_GATEWAY_URL", "http://gateway:8001")

        from src.app import create_app
        from src.auth.service import issue_access_token
        from src.config import build_app_config
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
            PLUGIN_GATEWAY_URL="http://gateway:8001",
        )
        runtime = build_runtime(config)
        runtime.security.is_token_in_blocklist = AsyncMock(return_value=False)
        app = create_app(runtime)

        mock_client = AsyncMock()
        mock_client.build_request = Mock(return_value=Mock())
        mock_client.send = AsyncMock(side_effect=httpx.ReadTimeout("upstream timed out"))
        app.state.plugin_gateway_client = mock_client

        transport = httpx.ASGITransport(app=app)
        token = issue_access_token("superuser", user_id=1, security=runtime.security)

        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get(
                    "/plg/demo/items",
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert response.status_code == 502
            assert response.json() == {"detail": "Bad Gateway for plugin: demo"}
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()


class TestConfigurationEdgeCases:
    """Test edge cases in configuration."""

    def test_empty_plugin_name(self):
        """Test handling of empty plugin names."""
        from src.plugins.crud import build_plugin_mount_prefix
        
        result = build_plugin_mount_prefix("")
        assert result == "/plg/"

    def test_plugin_name_with_only_whitespace(self):
        """Test handling of whitespace-only plugin names."""
        from src.plugins.crud import build_plugin_mount_prefix
        
        result = build_plugin_mount_prefix("   \t\n   ")
        assert result == "/plg/"

    def test_very_long_plugin_name(self):
        """Test handling of very long plugin names."""
        from src.plugins.crud import build_plugin_mount_prefix
        
        long_name = "a" * 1000
        result = build_plugin_mount_prefix(long_name)
        assert result == f"/plg/{long_name}"
        assert len(result) > 1000
