"""Unit tests for plugin CRUD operations."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from gateway_server.gateway import DiscoveredService
from src.database import Model
from src.plugins.crud import (
    build_plugin_mount_prefix,
    get_plugin_mapping,
    list_plugin_mappings,
    set_plugin_enabled,
    sync_plugin_mappings,
)
from src.plugins.models import PluginMapping


@pytest_asyncio.fixture
async def async_session():
    """Create an async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session_maker() as session:
        yield session
    
    await engine.dispose()


class TestBuildPluginMountPrefix:
    """Test mount prefix building."""

    def test_builds_correct_prefix(self):
        assert build_plugin_mount_prefix("demo") == "/plg/demo"
        assert build_plugin_mount_prefix("my_plugin") == "/plg/my_plugin"

    def test_strips_whitespace(self):
        assert build_plugin_mount_prefix("  demo  ") == "/plg/demo"
        assert build_plugin_mount_prefix("\tdemo\n") == "/plg/demo"

    def test_strips_slashes(self):
        assert build_plugin_mount_prefix("/demo/") == "/plg/demo"
        assert build_plugin_mount_prefix("///demo///") == "/plg/demo"

    def test_handles_empty_string(self):
        assert build_plugin_mount_prefix("") == "/plg/"
        assert build_plugin_mount_prefix("   ") == "/plg/"


@pytest.mark.asyncio
class TestListPluginMappings:
    """Test listing plugin mappings."""

    async def test_returns_empty_list_when_no_mappings(self, async_session):
        result = await list_plugin_mappings(async_session)
        assert result == []

    async def test_returns_all_mappings(self, async_session):
        # Create test mappings
        mapping1 = PluginMapping(
            plugin_name="alpha",
            service_name="alpha",
            mount_prefix="/plg/alpha",
            enabled=True,
        )
        mapping2 = PluginMapping(
            plugin_name="beta",
            service_name="beta",
            mount_prefix="/plg/beta",
            enabled=False,
        )
        async_session.add_all([mapping1, mapping2])
        await async_session.commit()

        result = await list_plugin_mappings(async_session)
        assert len(result) == 2
        names = [m.plugin_name for m in result]
        assert "alpha" in names
        assert "beta" in names

    async def test_orders_by_plugin_name(self, async_session):
        # Create mappings in reverse order
        for name in ["zulu", "alpha", "mike"]:
            mapping = PluginMapping(
                plugin_name=name,
                service_name=name,
                mount_prefix=f"/plg/{name}",
                enabled=True,
            )
            async_session.add(mapping)
        await async_session.commit()

        result = await list_plugin_mappings(async_session)
        names = [m.plugin_name for m in result]
        assert names == ["alpha", "mike", "zulu"]


@pytest.mark.asyncio
class TestGetPluginMapping:
    """Test getting a single plugin mapping."""

    async def test_returns_none_when_not_found(self, async_session):
        result = await get_plugin_mapping(async_session, "nonexistent")
        assert result is None

    async def test_returns_mapping_when_found(self, async_session):
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=True,
        )
        async_session.add(mapping)
        await async_session.commit()

        result = await get_plugin_mapping(async_session, "demo")
        assert result is not None
        assert result.plugin_name == "demo"
        assert result.service_name == "demo"

    async def test_returns_first_match_only(self, async_session):
        # This shouldn't happen due to unique constraint, but test the query
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=True,
        )
        async_session.add(mapping)
        await async_session.commit()

        result = await get_plugin_mapping(async_session, "demo")
        assert result is not None
        assert result.plugin_name == "demo"


@pytest.mark.asyncio
class TestSyncPluginMappings:
    """Test syncing plugin mappings with discovered services."""

    async def test_creates_new_mappings_for_discovered_services(self, async_session):
        services = [
            DiscoveredService(
                name="demo1",
                directory=Path("/tmp/demo1"),
                run_script=Path("/tmp/demo1/run.sh"),
            ),
            DiscoveredService(
                name="demo2",
                directory=Path("/tmp/demo2"),
                run_script=Path("/tmp/demo2/run.sh"),
            ),
        ]

        result = await sync_plugin_mappings(async_session, services)
        await async_session.commit()

        assert len(result) == 2
        assert result[0].plugin_name == "demo1"
        assert result[1].plugin_name == "demo2"
        assert all(m.enabled for m in result)

    async def test_preserves_existing_mappings(self, async_session):
        # Create existing mapping
        existing = PluginMapping(
            plugin_name="existing",
            service_name="existing",
            mount_prefix="/plg/existing",
            enabled=False,  # Disabled
        )
        async_session.add(existing)
        await async_session.commit()

        services = [
            DiscoveredService(
                name="existing",
                directory=Path("/tmp/existing"),
                run_script=Path("/tmp/existing/run.sh"),
            ),
        ]

        result = await sync_plugin_mappings(async_session, services)
        
        assert len(result) == 1
        assert result[0].plugin_name == "existing"
        assert result[0].enabled is False  # Preserved

    async def test_does_not_delete_missing_services(self, async_session):
        # Create mapping for service that won't be discovered
        orphaned = PluginMapping(
            plugin_name="orphaned",
            service_name="orphaned",
            mount_prefix="/plg/orphaned",
            enabled=True,
        )
        async_session.add(orphaned)
        await async_session.commit()

        services = [
            DiscoveredService(
                name="new_service",
                directory=Path("/tmp/new"),
                run_script=Path("/tmp/new/run.sh"),
            ),
        ]

        result = await sync_plugin_mappings(async_session, services)
        
        # Should return both existing and new
        assert len(result) == 2
        names = {m.plugin_name for m in result}
        assert "orphaned" in names
        assert "new_service" in names

    async def test_returns_sorted_list(self, async_session):
        services = [
            DiscoveredService(name="zulu", directory=Path("/z"), run_script=Path("/z/run.sh")),
            DiscoveredService(name="alpha", directory=Path("/a"), run_script=Path("/a/run.sh")),
            DiscoveredService(name="mike", directory=Path("/m"), run_script=Path("/m/run.sh")),
        ]

        result = await sync_plugin_mappings(async_session, services)
        names = [m.plugin_name for m in result]
        assert names == ["alpha", "mike", "zulu"]

    async def test_handles_empty_services_list(self, async_session):
        result = await sync_plugin_mappings(async_session, [])
        assert result == []


@pytest.mark.asyncio
class TestSetPluginEnabled:
    """Test enabling/disabling plugins."""

    async def test_enables_disabled_plugin(self, async_session):
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=False,
        )
        async_session.add(mapping)
        await async_session.commit()

        result = await set_plugin_enabled(async_session, plugin_name="demo", enabled=True)
        
        assert result is not None
        assert result.enabled is True

    async def test_disables_enabled_plugin(self, async_session):
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=True,
        )
        async_session.add(mapping)
        await async_session.commit()

        result = await set_plugin_enabled(async_session, plugin_name="demo", enabled=False)
        
        assert result is not None
        assert result.enabled is False

    async def test_returns_none_for_nonexistent_plugin(self, async_session):
        result = await set_plugin_enabled(async_session, plugin_name="nonexistent", enabled=True)
        assert result is None

    async def test_idempotent_enable(self, async_session):
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=True,
        )
        async_session.add(mapping)
        await async_session.commit()

        result = await set_plugin_enabled(async_session, plugin_name="demo", enabled=True)
        
        assert result is not None
        assert result.enabled is True

    async def test_idempotent_disable(self, async_session):
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=False,
        )
        async_session.add(mapping)
        await async_session.commit()

        result = await set_plugin_enabled(async_session, plugin_name="demo", enabled=False)
        
        assert result is not None
        assert result.enabled is False

    async def test_changes_are_flushed(self, async_session):
        mapping = PluginMapping(
            plugin_name="demo",
            service_name="demo",
            mount_prefix="/plg/demo",
            enabled=False,
        )
        async_session.add(mapping)
        await async_session.commit()

        await set_plugin_enabled(async_session, plugin_name="demo", enabled=True)
        
        # Query again to verify flush worked
        stmt = select(PluginMapping).where(PluginMapping.plugin_name == "demo")
        result = await async_session.execute(stmt)
        refreshed = result.scalar_one()
        assert refreshed.enabled is True
