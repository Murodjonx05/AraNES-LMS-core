from __future__ import annotations

from dataclasses import dataclass
import logging
from time import monotonic

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from src.database import DbSession
from src.plugins.crud import get_plugin_mapping, list_plugin_mappings, set_plugin_enabled
from src.plugins.schemas import PluginEnabledPatch, PluginMappingRead
from src.user_role.middlewares import require_permission
from src.user_role.permission import RBAC_CAN_MANAGE_PERMISSIONS

logger = logging.getLogger(__name__)
_DEFAULT_GATEWAY_SERVICES_CACHE_TTL_SECONDS = 2.0
_GATEWAY_SERVICES_CACHE_STATE_KEY = "_plugin_gateway_services_cache"


@dataclass(slots=True)
class GatewayServicesCacheEntry:
    gateway_url: str
    services: tuple[PluginMappingRead, ...]
    expires_at: float

plugins_router = APIRouter(
    prefix="/plugins",
    tags=["plugins"],
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)


async def _fetch_gateway_services(gateway_url: str) -> list[PluginMappingRead]:
    base = gateway_url.rstrip("/")
    url = f"{base}/services"
    data: dict | None = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch gateway services from %s: %s", url, exc)
        return []

    if not isinstance(data, dict):
        return []
    items = data.get("services", [])
    result: list[PluginMappingRead] = []
    for s in items:
        if not isinstance(s, dict) or "name" not in s:
            continue
        name = str(s["name"]).strip()
        if not name:
            continue
        result.append(
            PluginMappingRead(
                plugin_name=name,
                service_name=name,
                mount_prefix=s.get("mount_prefix", f"/plg/{name}"),
                enabled=True,
                discovered=True,
                running=s.get("status") == "running",
            )
        )
    return result


def _normalize_plugin_mapping_reads(
    services: list[PluginMappingRead] | list[dict],
) -> list[PluginMappingRead]:
    normalized: list[PluginMappingRead] = []
    for service in services:
        if isinstance(service, PluginMappingRead):
            normalized.append(service)
            continue
        normalized.append(PluginMappingRead.model_validate(service))
    return normalized


def _gateway_services_cache_ttl_seconds(request: Request) -> float:
    runtime = getattr(request.app.state, "runtime", None)
    configured = getattr(
        getattr(runtime, "config", None),
        "PLUGIN_GATEWAY_CACHE_TTL_SECONDS",
        _DEFAULT_GATEWAY_SERVICES_CACHE_TTL_SECONDS,
    )
    return max(0.0, float(configured))


def _read_gateway_services_cache(
    request: Request,
    gateway_url: str,
) -> list[PluginMappingRead] | None:
    cached = getattr(request.app.state, _GATEWAY_SERVICES_CACHE_STATE_KEY, None)
    if not isinstance(cached, GatewayServicesCacheEntry):
        return None
    if cached.gateway_url != gateway_url or cached.expires_at <= monotonic():
        return None
    return [service.model_copy(deep=True) for service in cached.services]


def _write_gateway_services_cache(
    request: Request,
    gateway_url: str,
    services: list[PluginMappingRead] | list[dict],
    *,
    ttl_seconds: float,
) -> list[PluginMappingRead]:
    normalized = _normalize_plugin_mapping_reads(services)
    if ttl_seconds <= 0:
        setattr(request.app.state, _GATEWAY_SERVICES_CACHE_STATE_KEY, None)
        return normalized
    cached_services = tuple(service.model_copy(deep=True) for service in normalized)
    setattr(
        request.app.state,
        _GATEWAY_SERVICES_CACHE_STATE_KEY,
        GatewayServicesCacheEntry(
            gateway_url=gateway_url,
            services=cached_services,
            expires_at=monotonic() + ttl_seconds,
        ),
    )
    return normalized


async def _get_gateway_services(
    request: Request,
    gateway_url: str,
) -> list[PluginMappingRead]:
    ttl_seconds = _gateway_services_cache_ttl_seconds(request)
    if ttl_seconds <= 0:
        return _normalize_plugin_mapping_reads(await _fetch_gateway_services(gateway_url))
    cached = _read_gateway_services_cache(request, gateway_url)
    if cached is not None:
        return cached
    services = await _fetch_gateway_services(gateway_url)
    return _write_gateway_services_cache(request, gateway_url, services, ttl_seconds=ttl_seconds)


def _serialize_db_mapping(mapping) -> PluginMappingRead:
    return PluginMappingRead(
        plugin_name=mapping.plugin_name,
        service_name=mapping.service_name,
        mount_prefix=mapping.mount_prefix,
        enabled=mapping.enabled,
        discovered=True,
        running=False,
    )


def _get_gateway_url(request: Request) -> str | None:
    runtime = getattr(request.app.state, "runtime", None)
    return getattr(getattr(runtime, "config", None), "PLUGIN_GATEWAY_URL", None)


@plugins_router.get("", response_model=list[PluginMappingRead])
async def get_plugins(request: Request, session: DbSession) -> list[PluginMappingRead]:
    gateway_url = _get_gateway_url(request)
    if gateway_url:
        return await _get_gateway_services(request, gateway_url)
    mappings = await list_plugin_mappings(session)
    return [_serialize_db_mapping(m) for m in mappings]


@plugins_router.patch("/{plugin_name}", response_model=PluginMappingRead)
async def patch_plugin_enabled(
    plugin_name: str,
    payload: PluginEnabledPatch,
    request: Request,
    session: DbSession,
) -> PluginMappingRead:
    gateway_url = _get_gateway_url(request)
    if gateway_url:
        raise HTTPException(
            status_code=405,
            detail="PATCH is not supported when using the plugin gateway. Gateway-managed plugins are read-only.",
        )
    mapping = await set_plugin_enabled(session, plugin_name=plugin_name, enabled=payload.enabled)
    if mapping is None:
        raise HTTPException(status_code=404, detail=f"Plugin mapping not found: {plugin_name}")
    await session.commit()
    return _serialize_db_mapping(mapping)
