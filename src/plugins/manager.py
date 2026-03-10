from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import httpx
from fastapi import HTTPException

from gateway_server.gateway import (
    DEFAULT_SERVICES_DIR,
    ManagedServiceRuntime,
    allocate_free_port,
    build_start_command,
    discover_services,
    fetch_service_openapi_documents,
    merge_openapi_documents,
    service_health_path,
    service_openapi_path,
    service_startup_timeout_seconds,
    shutdown_services,
    terminate_process,
    wait_for_service_ready,
)
from src.database import session_scope
from src.plugins.crud import sync_plugin_mappings
from src.plugins.models import PluginMapping
from src.runtime import RuntimeContext


logger = logging.getLogger("aranes.plugins")


class PluginManager:
    def __init__(
        self,
        *,
        services_root: Path = DEFAULT_SERVICES_DIR,
        start_port: int = 10000,
        readiness_timeout_seconds: float = 20.0,
    ) -> None:
        self.services_root = services_root
        self.start_port = start_port
        self.readiness_timeout_seconds = readiness_timeout_seconds
        self.registry: dict[str, ManagedServiceRuntime] = {}
        self._app: Any | None = None

    def bind_app(self, app: Any) -> None:
        self._app = app

    def invalidate_openapi_cache(self) -> None:
        if self._app is not None:
            self._app.openapi_schema = None

    def active_service(self, plugin_name: str) -> ManagedServiceRuntime | None:
        return self.registry.get(plugin_name)

    def is_running(self, plugin_name: str) -> bool:
        service = self.active_service(plugin_name)
        return service is not None and service.process.poll() is None

    async def startup(self, *, runtime: RuntimeContext | None) -> None:
        if runtime is None:
            return
        if not getattr(runtime.config, "PLUGIN_MANAGER_ENABLED", True):
            await shutdown_services(self.registry)
            self.invalidate_openapi_cache()
            return
        web_concurrency = int(str(os.getenv("WEB_CONCURRENCY", "1")).strip() or "1")
        if web_concurrency > 1:
            raise RuntimeError(
                "PLUGIN_MANAGER requires WEB_CONCURRENCY=1 because plugin processes are managed in-process."
            )
        await shutdown_services(self.registry)
        discovered_services = discover_services(self.services_root)
        async with session_scope(runtime=runtime) as session:
            mappings = await sync_plugin_mappings(session, discovered_services)
            await session.commit()

        discovered_by_service = {service.name: service for service in discovered_services}
        next_port = self.start_port
        for mapping in mappings:
            if not mapping.enabled:
                continue
            discovered_service = discovered_by_service.get(mapping.service_name)
            if discovered_service is None:
                logger.warning(
                    "Plugin %s is enabled in the database but the service directory %s is missing",
                    mapping.plugin_name,
                    mapping.service_name,
                )
                continue
            port = allocate_free_port(next_port)
            next_port = port + 1
            runtime_service = await self._start_plugin_process(
                mapping=mapping,
                discovered_service=discovered_service,
                port=port,
            )
            self.registry[mapping.plugin_name] = runtime_service

        await self.refresh_openapi_cache()

    async def shutdown(self) -> None:
        await shutdown_services(self.registry)
        self.invalidate_openapi_cache()

    async def refresh_openapi_cache(self) -> dict[str, dict[str, Any]]:
        documents = await fetch_service_openapi_documents(self.registry)
        self.invalidate_openapi_cache()
        return documents

    def cached_openapi_documents(self) -> dict[str, dict[str, Any]]:
        return {
            plugin_name: copy.deepcopy(service.openapi_cache)
            for plugin_name, service in self.registry.items()
            if service.openapi_cache is not None
        }

    async def _start_plugin_process(
        self,
        *,
        mapping: PluginMapping,
        discovered_service,
        port: int,
    ) -> ManagedServiceRuntime:
        manifest = discovered_service.manifest
        env = {
            **os.environ,
            "SERVICE_PORT": str(port),
            "SERVICE_PYTHON": sys.executable,
            "PLUGIN_NAME": mapping.plugin_name,
            "PLUGIN_MOUNT_PREFIX": mapping.mount_prefix,
        }
        command = build_start_command(discovered_service, port)
        process = subprocess.Popen(
            command,
            cwd=discovered_service.directory,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        service = ManagedServiceRuntime(
            name=mapping.plugin_name,
            directory=discovered_service.directory,
            run_script=discovered_service.run_script,
            port=port,
            base_url=f"http://127.0.0.1:{port}",
            process=process,
            manifest=manifest,
        )
        logger.info(
            "Starting plugin %s from service %s on http://127.0.0.1:%s",
            mapping.plugin_name,
            mapping.service_name,
            port,
        )
        try:
            await wait_for_service_ready(
                process=process,
                base_url=service.base_url,
                health_path=service_health_path(discovered_service),
                timeout_seconds=service_startup_timeout_seconds(
                    discovered_service,
                    self.readiness_timeout_seconds,
                ),
            )
        except Exception:
            await terminate_process(process)
            raise

        openapi_path = service_openapi_path(discovered_service)
        if openapi_path:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{service.base_url}{openapi_path}")
                    response.raise_for_status()
                    service.openapi_cache = response.json()
            except Exception as exc:
                logger.warning(
                    "Failed to fetch OpenAPI for plugin %s from service %s: %s",
                    mapping.plugin_name,
                    mapping.service_name,
                    exc,
                )
        logger.info(
            "Started plugin %s from service %s on http://127.0.0.1:%s (pid=%s)",
            mapping.plugin_name,
            mapping.service_name,
            port,
            process.pid,
        )
        return service

    async def apply_mapping_state(
        self,
        *,
        mapping: PluginMapping,
    ) -> None:
        current_runtime = self.registry.get(mapping.plugin_name)
        discovered_service = next(
            (service for service in discover_services(self.services_root) if service.name == mapping.service_name),
            None,
        )

        if not mapping.enabled:
            if current_runtime is not None:
                await terminate_process(current_runtime.process)
                self.registry.pop(mapping.plugin_name, None)
                self.invalidate_openapi_cache()
            return

        if current_runtime is not None and current_runtime.process.poll() is None:
            return

        if discovered_service is None:
            raise HTTPException(
                status_code=409,
                detail=f"Plugin service directory is missing: {mapping.service_name}",
            )

        port = allocate_free_port(self.start_port)
        self.registry[mapping.plugin_name] = await self._start_plugin_process(
            mapping=mapping,
            discovered_service=discovered_service,
            port=port,
        )
        self.invalidate_openapi_cache()

    def merge_plugin_openapi(self, core_schema: dict[str, Any]) -> dict[str, Any]:
        plugin_documents = self.cached_openapi_documents()
        if not plugin_documents:
            return core_schema

        merged_plugins = merge_openapi_documents(plugin_documents)
        merged_schema = copy.deepcopy(core_schema)
        merged_schema["paths"].update(merged_plugins.get("paths", {}))

        plugin_schemas = merged_plugins.get("components", {}).get("schemas", {})
        if plugin_schemas:
            components = merged_schema.setdefault("components", {})
            schemas = components.setdefault("schemas", {})
            schemas.update(plugin_schemas)

        if "tags" in merged_plugins:
            existing_tags = {tag.get("name") for tag in merged_schema.get("tags", [])}
            tags = merged_schema.setdefault("tags", [])
            for tag in merged_plugins["tags"]:
                tag_name = tag.get("name")
                if tag_name in existing_tags:
                    continue
                tags.append(tag)
                existing_tags.add(tag_name)
        return merged_schema
