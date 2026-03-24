from __future__ import annotations

from typing import Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.plugins.constants import plugin_mount_prefix
from src.plugins.models import PluginMapping


class SupportsDiscoveredPlugin(Protocol):
    name: str


def build_plugin_mount_prefix(plugin_name: str) -> str:
    return plugin_mount_prefix(plugin_name)


async def list_plugin_mappings(session: AsyncSession) -> list[PluginMapping]:
    result = await session.execute(select(PluginMapping).order_by(PluginMapping.plugin_name))
    return list(result.scalars())


async def get_plugin_mapping(session: AsyncSession, plugin_name: str) -> PluginMapping | None:
    result = await session.execute(
        select(PluginMapping).where(PluginMapping.plugin_name == plugin_name).limit(1)
    )
    return result.scalar_one_or_none()


async def create_plugin_mapping(
    session: AsyncSession,
    *,
    plugin_name: str,
    service_name: str,
    mount_prefix: str | None = None,
    enabled: bool = True,
) -> PluginMapping:
    mapping = PluginMapping(
        plugin_name=plugin_name,
        service_name=service_name,
        mount_prefix=mount_prefix or build_plugin_mount_prefix(plugin_name),
        enabled=enabled,
    )
    session.add(mapping)
    await session.flush()
    return mapping


async def sync_plugin_mappings(
    session: AsyncSession,
    discovered_services: Sequence[SupportsDiscoveredPlugin],
) -> list[PluginMapping]:
    # Unordered fetch: sort in Python once after sync (avoids DB ORDER BY on hot plugin discovery).
    result = await session.execute(select(PluginMapping))
    existing = list(result.scalars())
    existing_by_service = {mapping.service_name: mapping for mapping in existing}

    created: list[PluginMapping] = []
    for service in discovered_services:
        if service.name in existing_by_service:
            continue
        created.append(
            PluginMapping(
                plugin_name=service.name,
                service_name=service.name,
                mount_prefix=build_plugin_mount_prefix(service.name),
                enabled=True,
            )
        )

    if created:
        session.add_all(created)
        await session.flush()
        existing.extend(created)

    existing.sort(key=lambda mapping: mapping.plugin_name)
    return existing


async def set_plugin_enabled(
    session: AsyncSession,
    *,
    plugin_name: str,
    enabled: bool,
) -> PluginMapping | None:
    mapping = await get_plugin_mapping(session, plugin_name)
    if mapping is None:
        return None
    mapping.enabled = enabled
    await session.flush()
    return mapping


async def delete_plugin_mapping(session: AsyncSession, plugin_name: str) -> bool:
    mapping = await get_plugin_mapping(session, plugin_name)
    if mapping is None:
        return False
    await session.delete(mapping)
    await session.flush()
    return True
