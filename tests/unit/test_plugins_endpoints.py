from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.plugins.endpoints import _fetch_gateway_services, _get_gateway_services
from src.plugins.schemas import PluginMappingRead


@pytest.mark.asyncio
async def test_fetch_gateway_services_skips_malformed_items() -> None:
    mock_response = Mock(status_code=200)
    mock_response.json = Mock(
        return_value={
            "services": [
                None,
                {},
                {"name": "   "},
                {"name": "demo", "mount_prefix": "/plg/demo", "status": "running"},
            ]
        }
    )
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client_manager = AsyncMock()
    mock_client_manager.__aenter__.return_value = mock_client
    mock_client_manager.__aexit__.return_value = False

    with patch("src.plugins.endpoints.httpx.AsyncClient", return_value=mock_client_manager):
        services = await _fetch_gateway_services("http://gateway:8001")

    assert len(services) == 1
    assert services[0].plugin_name == "demo"
    assert services[0].running is True


@pytest.mark.asyncio
async def test_get_gateway_services_uses_request_scoped_cache() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    fetch_mock = AsyncMock(
        return_value=[
            PluginMappingRead(
                plugin_name="demo",
                service_name="demo",
                mount_prefix="/plg/demo",
                enabled=True,
                discovered=True,
                running=True,
            )
        ]
    )

    with patch("src.plugins.endpoints._fetch_gateway_services", new=fetch_mock):
        first = await _get_gateway_services(request, "http://gateway:8001")
        first[0].plugin_name = "mutated"
        second = await _get_gateway_services(request, "http://gateway:8001")

    assert fetch_mock.await_count == 1
    assert second[0].plugin_name == "demo"


@pytest.mark.asyncio
async def test_get_gateway_services_can_disable_cache_via_runtime_config() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                runtime=SimpleNamespace(
                    config=SimpleNamespace(PLUGIN_GATEWAY_CACHE_TTL_SECONDS=0.0)
                )
            )
        )
    )
    fetch_mock = AsyncMock(
        return_value=[
            PluginMappingRead(
                plugin_name="demo",
                service_name="demo",
                mount_prefix="/plg/demo",
                enabled=True,
                discovered=True,
                running=True,
            )
        ]
    )

    with patch("src.plugins.endpoints._fetch_gateway_services", new=fetch_mock):
        await _get_gateway_services(request, "http://gateway:8001")
        await _get_gateway_services(request, "http://gateway:8001")

    assert fetch_mock.await_count == 2
