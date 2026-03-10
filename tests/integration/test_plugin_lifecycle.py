"""Integration tests for complete plugin lifecycle management."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.plugins.manager import PluginManager
from gateway_server.gateway import DiscoveredService, ManagedServiceRuntime, PluginManifest


class TestPluginLifecycleIntegration:
    """Test complete plugin lifecycle from discovery to shutdown."""

    @pytest.mark.asyncio
    async def test_plugin_manager_startup_with_no_plugins(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test plugin manager starts successfully with no plugins."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")
        monkeypatch.setenv("PLUGIN_MANAGER_ENABLED", "true")

        from src.config import build_app_config
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_MANAGER_ENABLED=True,
        )
        runtime = build_runtime(config)

        services_root = tmp_path / "services"
        services_root.mkdir()

        manager = PluginManager(services_root=services_root)

        try:
            await manager.startup(runtime=runtime)
            assert len(manager.registry) == 0
        finally:
            await manager.shutdown()
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_plugin_manager_startup_with_disabled_plugin(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test plugin manager skips disabled plugins."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.config import build_app_config
        from src.database import session_scope
        from src.plugins.crud import sync_plugin_mappings
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_MANAGER_ENABLED=True,
        )
        runtime = build_runtime(config)

        services_root = tmp_path / "services"
        service_dir = services_root / "disabled_plugin"
        service_dir.mkdir(parents=True)
        (service_dir / "run.sh").write_text("#!/bin/bash\necho 'test'")

        # Create and disable the plugin in DB
        async with session_scope(runtime=runtime) as session:
            from gateway_server.gateway import discover_services
            services = discover_services(services_root)
            mappings = await sync_plugin_mappings(session, services)
            for mapping in mappings:
                mapping.enabled = False
            await session.commit()

        manager = PluginManager(services_root=services_root)

        try:
            await manager.startup(runtime=runtime)
            assert len(manager.registry) == 0
        finally:
            await manager.shutdown()
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_plugin_manager_openapi_cache_invalidation(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test OpenAPI cache invalidation on plugin changes."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.config import build_app_config
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_MANAGER_ENABLED=True,
        )
        runtime = build_runtime(config)

        services_root = tmp_path / "services"
        services_root.mkdir()

        manager = PluginManager(services_root=services_root)

        # Create mock app
        mock_app = Mock()
        mock_app.openapi_schema = {"cached": "schema"}
        manager.bind_app(mock_app)

        try:
            await manager.startup(runtime=runtime)
            
            # Invalidate cache
            manager.invalidate_openapi_cache()
            assert mock_app.openapi_schema is None
        finally:
            await manager.shutdown()
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_plugin_manager_checks_web_concurrency(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test plugin manager fails with WEB_CONCURRENCY > 1."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")
        monkeypatch.setenv("WEB_CONCURRENCY", "4")

        from src.config import build_app_config
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_MANAGER_ENABLED=True,
        )
        runtime = build_runtime(config)

        services_root = tmp_path / "services"
        services_root.mkdir()

        manager = PluginManager(services_root=services_root)

        try:
            with pytest.raises(RuntimeError, match="WEB_CONCURRENCY=1"):
                await manager.startup(runtime=runtime)
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_plugin_manager_is_running_check(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test plugin manager running status check."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.config import build_app_config
        from src.runtime import build_runtime, reset_default_runtime

        reset_default_runtime()
        config = replace(
            build_app_config(),
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_MANAGER_ENABLED=True,
        )
        runtime = build_runtime(config)

        services_root = tmp_path / "services"
        services_root.mkdir()

        manager = PluginManager(services_root=services_root)

        # Add mock service
        mock_process = Mock()
        mock_process.poll.return_value = None  # Running
        manager.registry["test_plugin"] = ManagedServiceRuntime(
            name="test_plugin",
            directory=tmp_path,
            run_script=tmp_path / "run.sh",
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
        )

        try:
            assert manager.is_running("test_plugin") is True
            assert manager.is_running("nonexistent") is False

            # Simulate process death
            mock_process.poll.return_value = 1
            assert manager.is_running("test_plugin") is False
        finally:
            await manager.shutdown()
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_plugin_manager_start_process_respects_manifest_settings(self, tmp_path: Path):
        manager = PluginManager(services_root=tmp_path, readiness_timeout_seconds=20.0)
        mapping = Mock(plugin_name="demo", service_name="demo", mount_prefix="/plg/demo")
        discovered_service = DiscoveredService(
            name="demo",
            directory=tmp_path,
            run_script=tmp_path / "run.sh",
            manifest=PluginManifest(
                plugin_name="demo",
                version="1.0.0",
                runtime="python",
                start_command=["python", "app.py", "--port", "${PORT}"],
                health_path="/healthz",
                openapi_path="/schema.json",
                startup_timeout_seconds=12.5,
                auto_start=True,
            ),
        )
        mock_process = Mock(pid=12345)

        with (
            patch("src.plugins.manager.subprocess.Popen", return_value=mock_process) as popen_mock,
            patch("src.plugins.manager.wait_for_service_ready", new=AsyncMock()) as ready_mock,
            patch("src.plugins.manager.httpx.AsyncClient") as client_class,
        ):
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.json.return_value = {"openapi": "3.1.0", "paths": {}}
            mock_client.get.return_value = mock_response
            client_class.return_value.__aenter__.return_value = mock_client

            runtime_service = await manager._start_plugin_process(
                mapping=mapping,
                discovered_service=discovered_service,
                port=10077,
            )

        popen_mock.assert_called_once()
        assert popen_mock.call_args.args[0] == ["python", "app.py", "--port", "10077"]
        assert popen_mock.call_args.kwargs["cwd"] == tmp_path
        assert popen_mock.call_args.kwargs["stdin"] == subprocess.DEVNULL
        assert popen_mock.call_args.kwargs["env"]["SERVICE_PORT"] == "10077"
        assert popen_mock.call_args.kwargs["env"]["PLUGIN_NAME"] == "demo"
        assert popen_mock.call_args.kwargs["env"]["PLUGIN_MOUNT_PREFIX"] == "/plg/demo"
        ready_mock.assert_awaited_once_with(
            process=mock_process,
            base_url="http://127.0.0.1:10077",
            health_path="/healthz",
            timeout_seconds=12.5,
        )
        mock_client.get.assert_awaited_once_with("http://127.0.0.1:10077/schema.json")
        assert runtime_service.manifest is discovered_service.manifest
        assert runtime_service.openapi_cache == {"openapi": "3.1.0", "paths": {}}

    @pytest.mark.asyncio
    async def test_plugin_manager_cached_openapi_documents(
        self,
        tmp_path: Path,
    ):
        """Test cached OpenAPI documents retrieval."""
        services_root = tmp_path / "services"
        services_root.mkdir()

        manager = PluginManager(services_root=services_root)

        # Add services with OpenAPI cache
        mock_process = Mock()
        mock_process.poll.return_value = None

        openapi_doc = {"openapi": "3.1.0", "paths": {"/test": {}}}
        
        manager.registry["plugin1"] = ManagedServiceRuntime(
            name="plugin1",
            directory=tmp_path,
            run_script=tmp_path / "run.sh",
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
            openapi_cache=openapi_doc,
        )

        manager.registry["plugin2"] = ManagedServiceRuntime(
            name="plugin2",
            directory=tmp_path,
            run_script=tmp_path / "run.sh",
            port=10002,
            base_url="http://127.0.0.1:10002",
            process=mock_process,
            openapi_cache=None,  # No cache
        )

        cached = manager.cached_openapi_documents()
        
        assert "plugin1" in cached
        assert "plugin2" not in cached
        assert cached["plugin1"]["paths"] == {"/test": {}}
        
        # Verify it's a deep copy
        cached["plugin1"]["paths"]["/modified"] = {}
        assert "/modified" not in manager.registry["plugin1"].openapi_cache["paths"]


class TestPluginEndpointsIntegration:
    """Test plugin endpoints with different states."""

    @pytest.mark.asyncio
    async def test_get_plugins_with_gateway_url(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test GET /api/v1/plugins with gateway URL configured."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

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
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_GATEWAY_URL="http://gateway:8001",
        )
        runtime = build_runtime(config)
        app = create_app(runtime)
        transport = httpx.ASGITransport(app=app)
        token = issue_access_token("superuser", user_id=1, security=runtime.security)

        async def _fake_fetch_gateway_services(_gateway_url: str):
            return [
                {
                    "plugin_name": "demo_plugin",
                    "service_name": "demo_plugin",
                    "mount_prefix": "/plg/demo_plugin",
                    "enabled": True,
                    "discovered": True,
                    "running": True,
                }
            ]

        try:
            with patch("src.plugins.endpoints._fetch_gateway_services", side_effect=_fake_fetch_gateway_services):
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    response = await client.get(
                        "/api/v1/plugins",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            assert response.status_code == 200
            plugins = response.json()
            assert len(plugins) == 1
            assert plugins[0]["plugin_name"] == "demo_plugin"
            assert plugins[0]["running"] is True
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_patch_plugin_fails_with_gateway_url(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test PATCH /api/v1/plugins/{name} fails when gateway is configured."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

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
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_GATEWAY_URL="http://gateway:8001",
        )
        runtime = build_runtime(config)
        app = create_app(runtime)
        transport = httpx.ASGITransport(app=app)
        token = issue_access_token("superuser", user_id=1, security=runtime.security)

        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.patch(
                    "/api/v1/plugins/demo",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"enabled": False},
                )

            assert response.status_code == 405
            assert "read-only" in response.json()["detail"].lower()
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()


class TestPluginProxyIntegration:
    """Test plugin proxy functionality with various states."""

    @pytest.mark.asyncio
    async def test_proxy_preserves_request_body(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test proxy forwards request body correctly."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

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
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_GATEWAY_URL="http://gateway:8001",
        )
        runtime = build_runtime(config)
        app = create_app(runtime)

        # Setup mock gateway client
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.headers = {"content-type": "application/json"}
        
        async def mock_aiter_raw():
            yield b'{"id": 123}'
        
        mock_response.aiter_raw = mock_aiter_raw
        mock_response.aclose = AsyncMock()

        captured_body = None

        async def mock_send(request, **kwargs):
            nonlocal captured_body
            captured_body = request.content
            return mock_response

        mock_client.build_request = Mock(return_value=Mock(content=b'{"name": "test"}'))
        mock_client.send = mock_send
        app.state.plugin_gateway_client = mock_client

        transport = httpx.ASGITransport(app=app)
        token = issue_access_token("superuser", user_id=1, security=runtime.security)

        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.post(
                    "/plg/demo/items",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": "test"},
                )

            assert response.status_code == 201
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()

    @pytest.mark.asyncio
    async def test_proxy_handles_gateway_connection_error(
        self,
        seeded_db_template: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test proxy returns 502 on gateway connection error."""
        db_path = tmp_path / "test.sqlite3"
        shutil.copyfile(seeded_db_template, db_path)

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
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
            PLUGIN_GATEWAY_URL="http://gateway:8001",
        )
        runtime = build_runtime(config)
        app = create_app(runtime)

        # Setup mock gateway client that fails
        mock_client = AsyncMock()
        mock_client.build_request = Mock(return_value=Mock())
        mock_client.send = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
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
            assert "Bad Gateway" in response.json()["detail"]
        finally:
            await runtime.cache_service.close()
            await runtime.engine.dispose()
            reset_default_runtime()
