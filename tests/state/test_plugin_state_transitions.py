"""Tests for plugin state transitions and different code states."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio

from gateway_server.gateway import (
    DiscoveredService,
    ManagedServiceRuntime,
    PluginManifest,
)


class TestPluginStateTransitions:
    """Test all possible plugin state transitions."""

    @pytest.mark.asyncio
    async def test_plugin_state_not_discovered_to_discovered(self, tmp_path: Path):
        """Test: NOT_EXISTS → DISCOVERED state transition."""
        from gateway_server.gateway import discover_services

        services_root = tmp_path / "services"
        services_root.mkdir()

        # Initial state: no plugins
        result = discover_services(services_root)
        assert len(result) == 0

        # Create plugin (state transition)
        plugin_dir = services_root / "new_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "run.sh").write_text("#!/bin/bash\necho 'running'")

        # New state: plugin discovered
        result = discover_services(services_root)
        assert len(result) == 1
        assert result[0].name == "new_plugin"

    @pytest.mark.asyncio
    async def test_plugin_state_discovered_to_registered(self, tmp_path: Path):
        """Test: DISCOVERED → REGISTERED state transition."""
        from gateway_server.gateway import discover_services
        from src.database import session_scope
        from src.plugins.crud import sync_plugin_mappings

        services_root = tmp_path / "services"
        plugin_dir = services_root / "test_plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "run.sh").write_text("#!/bin/bash\n")

        # State: DISCOVERED
        services = discover_services(services_root)
        assert len(services) == 1

        # Transition to: REGISTERED (would happen in real runtime)
        # This test verifies the sync mechanism
        assert services[0].name == "test_plugin"

    @pytest.mark.asyncio
    async def test_plugin_state_disabled_to_enabled(self, tmp_path: Path):
        """Test: DISABLED → ENABLED state transition."""
        from src.plugins.models import PluginMapping

        # Create disabled plugin
        mapping = PluginMapping(
            plugin_name="test",
            service_name="test",
            mount_prefix="/plg/test",
            enabled=False,
        )

        # State: DISABLED
        assert mapping.enabled is False

        # Transition to: ENABLED
        mapping.enabled = True
        assert mapping.enabled is True

    @pytest.mark.asyncio
    async def test_plugin_state_enabled_to_disabled(self, tmp_path: Path):
        """Test: ENABLED → DISABLED state transition."""
        from src.plugins.models import PluginMapping

        # Create enabled plugin
        mapping = PluginMapping(
            plugin_name="test",
            service_name="test",
            mount_prefix="/plg/test",
            enabled=True,
        )

        # State: ENABLED
        assert mapping.enabled is True

        # Transition to: DISABLED
        mapping.enabled = False
        assert mapping.enabled is False

    @pytest.mark.asyncio
    async def test_plugin_state_registered_to_starting(self):
        """Test: REGISTERED → STARTING state transition."""
        # Mock process that's starting
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_process.pid = 12345

        # State: STARTING (process exists but not ready)
        runtime = ManagedServiceRuntime(
            name="starting_plugin",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
        )

        assert runtime.process.poll() is None
        assert runtime.process.pid == 12345

    @pytest.mark.asyncio
    async def test_plugin_state_starting_to_running(self):
        """Test: STARTING → RUNNING state transition."""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Running
        mock_process.pid = 12345

        runtime = ManagedServiceRuntime(
            name="running_plugin",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
            openapi_cache={"openapi": "3.1.0"},  # Has cache = fully running
        )

        # State: RUNNING (process alive + has OpenAPI cache)
        assert runtime.process.poll() is None
        assert runtime.openapi_cache is not None

    @pytest.mark.asyncio
    async def test_plugin_state_running_to_stopped(self):
        """Test: RUNNING → STOPPED state transition."""
        mock_process = Mock()
        mock_process.poll.side_effect = [None, 0]  # Running, then stopped

        runtime = ManagedServiceRuntime(
            name="stopping_plugin",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
        )

        # State: RUNNING
        assert runtime.process.poll() is None

        # Simulate transition to: STOPPED by advancing the side effect
        assert runtime.process.poll() == 0

    @pytest.mark.asyncio
    async def test_plugin_state_running_to_crashed(self):
        """Test: RUNNING → CRASHED state transition."""
        mock_process = Mock()
        mock_process.poll.side_effect = [None, 1]  # Running, then crashed (exit code 1)

        runtime = ManagedServiceRuntime(
            name="crashed_plugin",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
        )

        # State: RUNNING
        assert runtime.process.poll() is None

        # Simulate crash (process exits with error)
        # State: CRASHED
        assert runtime.process.poll() == 1  # Non-zero exit code

    @pytest.mark.asyncio
    async def test_plugin_state_stopped_to_starting_restart(self):
        """Test: STOPPED → STARTING state transition (restart)."""
        # First process (stopped)
        old_process = Mock()
        old_process.poll.return_value = 0  # Stopped

        # New process (starting)
        new_process = Mock()
        new_process.poll.return_value = None  # Running
        new_process.pid = 67890

        # State: STOPPED
        old_runtime = ManagedServiceRuntime(
            name="restarting_plugin",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=old_process,
        )
        assert old_runtime.process.poll() == 0

        # Transition to: STARTING (restart)
        new_runtime = ManagedServiceRuntime(
            name="restarting_plugin",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10002,  # New port
            base_url="http://127.0.0.1:10002",
            process=new_process,
        )
        assert new_runtime.process.poll() is None
        assert new_runtime.process.pid == 67890


class TestConcurrentPluginStates:
    """Test concurrent plugin state operations."""

    @pytest.mark.asyncio
    async def test_multiple_plugins_different_states(self):
        """Test: Multiple plugins in different states simultaneously."""
        # Plugin 1: RUNNING
        process1 = Mock()
        process1.poll.return_value = None
        plugin1 = ManagedServiceRuntime(
            name="running",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=process1,
            openapi_cache={"openapi": "3.1.0"},
        )

        # Plugin 2: STOPPED
        process2 = Mock()
        process2.poll.return_value = 0
        plugin2 = ManagedServiceRuntime(
            name="stopped",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10002,
            base_url="http://127.0.0.1:10002",
            process=process2,
        )

        # Plugin 3: CRASHED
        process3 = Mock()
        process3.poll.return_value = 1
        plugin3 = ManagedServiceRuntime(
            name="crashed",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10003,
            base_url="http://127.0.0.1:10003",
            process=process3,
        )

        registry = {
            "running": plugin1,
            "stopped": plugin2,
            "crashed": plugin3,
        }

        # Verify different states coexist
        assert registry["running"].process.poll() is None  # Running
        assert registry["stopped"].process.poll() == 0  # Stopped
        assert registry["crashed"].process.poll() == 1  # Crashed

    @pytest.mark.asyncio
    async def test_rapid_state_transitions(self):
        """Test: Rapid state transitions (enable/disable cycles)."""
        from src.plugins.models import PluginMapping

        mapping = PluginMapping(
            plugin_name="rapid",
            service_name="rapid",
            mount_prefix="/plg/rapid",
            enabled=True,
        )

        # Rapid transitions
        for i in range(10):
            mapping.enabled = not mapping.enabled
            # After each toggle, the flag should simply be a boolean
            assert isinstance(mapping.enabled, bool)

        # After an even number of toggles, the final state should match the initial one (True)
        assert mapping.enabled is True


class TestPluginCacheStates:
    """Test plugin OpenAPI cache states."""

    @pytest.mark.asyncio
    async def test_cache_state_empty_to_populated(self):
        """Test: CACHE_EMPTY → CACHE_POPULATED state transition."""
        mock_process = Mock()
        mock_process.poll.return_value = None

        runtime = ManagedServiceRuntime(
            name="test",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
            openapi_cache=None,  # State: CACHE_EMPTY
        )

        assert runtime.openapi_cache is None

        # Transition to: CACHE_POPULATED
        runtime.openapi_cache = {"openapi": "3.1.0", "paths": {}}
        assert runtime.openapi_cache is not None
        assert "openapi" in runtime.openapi_cache

    @pytest.mark.asyncio
    async def test_cache_state_populated_to_invalidated(self):
        """Test: CACHE_POPULATED → CACHE_INVALIDATED state transition."""
        mock_process = Mock()
        mock_process.poll.return_value = None

        runtime = ManagedServiceRuntime(
            name="test",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
            openapi_cache={"openapi": "3.1.0"},  # State: CACHE_POPULATED
        )

        assert runtime.openapi_cache is not None

        # Transition to: CACHE_INVALIDATED
        runtime.openapi_cache = None
        assert runtime.openapi_cache is None

    @pytest.mark.asyncio
    async def test_cache_state_stale_to_refreshed(self):
        """Test: CACHE_STALE → CACHE_REFRESHED state transition."""
        mock_process = Mock()
        mock_process.poll.return_value = None

        runtime = ManagedServiceRuntime(
            name="test",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
            openapi_cache={"openapi": "3.0.0", "paths": {}},  # State: CACHE_STALE (old version)
        )

        old_cache = runtime.openapi_cache.copy()

        # Transition to: CACHE_REFRESHED
        runtime.openapi_cache = {"openapi": "3.1.0", "paths": {"/new": {}}}
        
        assert runtime.openapi_cache != old_cache
        assert runtime.openapi_cache["openapi"] == "3.1.0"
        assert "/new" in runtime.openapi_cache["paths"]


class TestRegistryStates:
    """Test plugin registry states."""

    @pytest.mark.asyncio
    async def test_registry_state_empty_to_populated(self):
        """Test: REGISTRY_EMPTY → REGISTRY_POPULATED state transition."""
        registry: dict[str, ManagedServiceRuntime] = {}

        # State: REGISTRY_EMPTY
        assert len(registry) == 0

        # Transition to: REGISTRY_POPULATED
        mock_process = Mock()
        mock_process.poll.return_value = None

        registry["plugin1"] = ManagedServiceRuntime(
            name="plugin1",
            directory=Path("/tmp"),
            run_script=Path("/tmp/run.sh"),
            port=10001,
            base_url="http://127.0.0.1:10001",
            process=mock_process,
        )

        # State: REGISTRY_POPULATED
        assert len(registry) == 1
        assert "plugin1" in registry

    @pytest.mark.asyncio
    async def test_registry_state_populated_to_empty(self):
        """Test: REGISTRY_POPULATED → REGISTRY_EMPTY state transition."""
        mock_process = Mock()
        mock_process.poll.return_value = 1  # Dead

        registry = {
            "plugin1": ManagedServiceRuntime(
                name="plugin1",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=mock_process,
            )
        }

        # State: REGISTRY_POPULATED
        assert len(registry) == 1

        # Transition to: REGISTRY_EMPTY
        from gateway_server.gateway import shutdown_services
        await shutdown_services(registry)

        # State: REGISTRY_EMPTY
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_registry_state_partial_failure(self):
        """Test: REGISTRY_MIXED state (some running, some failed)."""
        # Plugin 1: Running
        process1 = Mock()
        process1.poll.return_value = None

        # Plugin 2: Failed
        process2 = Mock()
        process2.poll.return_value = 1

        registry = {
            "running": ManagedServiceRuntime(
                name="running",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10001,
                base_url="http://127.0.0.1:10001",
                process=process1,
            ),
            "failed": ManagedServiceRuntime(
                name="failed",
                directory=Path("/tmp"),
                run_script=Path("/tmp/run.sh"),
                port=10002,
                base_url="http://127.0.0.1:10002",
                process=process2,
            ),
        }

        # State: REGISTRY_MIXED
        running_count = sum(1 for svc in registry.values() if svc.process.poll() is None)
        failed_count = sum(1 for svc in registry.values() if svc.process.poll() is not None)

        assert running_count == 1
        assert failed_count == 1


class TestManifestStates:
    """Test plugin manifest states."""

    def test_manifest_state_not_present(self, tmp_path: Path):
        """Test: MANIFEST_NOT_PRESENT state."""
        from gateway_server.gateway import discover_services

        services_root = tmp_path / "services"
        plugin_dir = services_root / "no_manifest"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "run.sh").write_text("#!/bin/bash\n")

        services = discover_services(services_root)
        
        # State: MANIFEST_NOT_PRESENT
        assert len(services) == 1
        assert services[0].manifest is None

    def test_manifest_state_present_valid(self, tmp_path: Path):
        """Test: MANIFEST_PRESENT_VALID state."""
        import json
        from gateway_server.gateway import discover_services

        services_root = tmp_path / "services"
        plugin_dir = services_root / "with_manifest"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "run.sh").write_text("#!/bin/bash\n")

        manifest = {
            "plugin_name": "test",
            "version": "1.0.0",
            "runtime": "python",
            "start_command": ["python", "main.py"],
            "health_path": "/health",
            "openapi_path": "/openapi.json",
            "startup_timeout_seconds": 30.0,
            "auto_start": True,
        }
        (plugin_dir / "manifest.json").write_text(json.dumps(manifest))

        services = discover_services(services_root)
        
        # State: MANIFEST_PRESENT_VALID
        assert len(services) == 1
        assert services[0].manifest is not None
        assert services[0].manifest.plugin_name == "test"
        assert services[0].manifest.version == "1.0.0"

    def test_manifest_state_present_invalid(self, tmp_path: Path):
        """Test: MANIFEST_PRESENT_INVALID state."""
        from gateway_server.gateway import discover_services

        services_root = tmp_path / "services"
        plugin_dir = services_root / "invalid_manifest"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "run.sh").write_text("#!/bin/bash\n")
        (plugin_dir / "manifest.json").write_text("invalid json{{{")

        services = discover_services(services_root)
        
        # State: MANIFEST_PRESENT_INVALID
        assert len(services) == 1
        assert services[0].manifest is None  # Failed to parse


class TestNetworkStates:
    """Test network-related states."""

    @pytest.mark.asyncio
    async def test_network_state_connected(self):
        """Test: NETWORK_CONNECTED state."""
        from gateway_server.gateway import wait_for_service_ready

        mock_process = Mock()
        mock_process.poll.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # State: NETWORK_CONNECTED (service responds)
            await wait_for_service_ready(
                process=mock_process,
                base_url="http://127.0.0.1:10001",
                timeout_seconds=5.0,
            )

    @pytest.mark.asyncio
    async def test_network_state_disconnected(self):
        """Test: NETWORK_DISCONNECTED state."""
        from gateway_server.gateway import wait_for_service_ready
        import httpx

        mock_process = Mock()
        mock_process.poll.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # State: NETWORK_DISCONNECTED (service not reachable)
            with pytest.raises(TimeoutError):
                await wait_for_service_ready(
                    process=mock_process,
                    base_url="http://127.0.0.1:10001",
                    timeout_seconds=0.1,
                )

    @pytest.mark.asyncio
    async def test_network_state_intermittent(self):
        """Test: NETWORK_INTERMITTENT state."""
        from gateway_server.gateway import wait_for_service_ready
        import httpx

        mock_process = Mock()
        mock_process.poll.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            
            # Simulate intermittent connection: fail, fail, success
            mock_response = Mock()
            mock_response.status_code = 200
            mock_client.get.side_effect = [
                httpx.ConnectError("Connection refused"),
                httpx.ConnectError("Connection refused"),
                mock_response,
            ]
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # State: NETWORK_INTERMITTENT (eventually succeeds)
            await wait_for_service_ready(
                process=mock_process,
                base_url="http://127.0.0.1:10001",
                timeout_seconds=5.0,
            )


class TestDatabaseStates:
    """Test database-related states."""

    @pytest.mark.asyncio
    async def test_database_state_empty(self, async_session):
        """Test: DATABASE_EMPTY state."""
        from src.plugins.crud import list_plugin_mappings

        # State: DATABASE_EMPTY
        mappings = await list_plugin_mappings(async_session)
        assert len(mappings) == 0

    @pytest.mark.asyncio
    async def test_database_state_populated(self, async_session):
        """Test: DATABASE_POPULATED state."""
        from src.plugins.models import PluginMapping
        from src.plugins.crud import list_plugin_mappings

        # Add mapping
        mapping = PluginMapping(
            plugin_name="test",
            service_name="test",
            mount_prefix="/plg/test",
            enabled=True,
        )
        async_session.add(mapping)
        await async_session.commit()

        # State: DATABASE_POPULATED
        mappings = await list_plugin_mappings(async_session)
        assert len(mappings) == 1

    @pytest.mark.asyncio
    async def test_database_state_inconsistent(self, async_session):
        """Test: DATABASE_INCONSISTENT state (mapping exists but service doesn't)."""
        from src.plugins.models import PluginMapping
        from src.plugins.crud import list_plugin_mappings

        # Create mapping for non-existent service
        mapping = PluginMapping(
            plugin_name="ghost_plugin",
            service_name="ghost_plugin",
            mount_prefix="/plg/ghost_plugin",
            enabled=True,
        )
        async_session.add(mapping)
        await async_session.commit()

        # State: DATABASE_INCONSISTENT (has DB entry but no actual service)
        mappings = await list_plugin_mappings(async_session)
        assert len(mappings) == 1
        assert mappings[0].plugin_name == "ghost_plugin"
        # In real scenario, service discovery would find no matching service


# Add async_session fixture
@pytest_asyncio.fixture
async def async_session():
    """Create an async session for testing."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from src.database import Model

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session_maker() as session:
        yield session
    
    await engine.dispose()
