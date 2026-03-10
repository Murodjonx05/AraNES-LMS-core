from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask


logger = logging.getLogger("gateway_server")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SERVICES_DIR = BASE_DIR.parent / "services"
START_PORT = 10000
READINESS_TIMEOUT_SECONDS = 20.0
PROCESS_SHUTDOWN_TIMEOUT_SECONDS = 10.0
PUBLIC_PLUGIN_PREFIX = "/plg"

# RFC 2616 hop-by-hop headers that must not be forwarded by proxies
# Note: This matches src/http/constants.py - kept in sync for gateway independence
HOP_BY_HOP_HEADERS = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})


def public_plugin_prefix(service_name: str) -> str:
    return f"{PUBLIC_PLUGIN_PREFIX}/{service_name}"


def to_internal_plugin_path(public_path: str, service_name: str) -> str:
    prefix = public_plugin_prefix(service_name)
    normalized_path = public_path if public_path.startswith("/") else f"/{public_path}"
    if normalized_path == prefix:
        return "/"
    if normalized_path.startswith(f"{prefix}/"):
        return normalized_path[len(prefix) :]
    return normalized_path


def to_public_openapi_paths(document_paths: dict[str, Any], service_name: str) -> dict[str, Any]:
    prefix = public_plugin_prefix(service_name)
    rewritten_paths: dict[str, Any] = {}
    for path_name, path_item in document_paths.items():
        normalized_path = path_name if path_name.startswith("/") else f"/{path_name}"
        if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
            public_path = normalized_path
        elif normalized_path == "/":
            public_path = prefix
        else:
            public_path = f"{prefix}{normalized_path}"
        rewritten_paths[public_path] = path_item
    return rewritten_paths


@dataclass(slots=True)
class PluginManifest:
    plugin_name: str
    version: str
    runtime: str
    start_command: list[str]
    health_path: str
    openapi_path: str | None
    startup_timeout_seconds: float
    auto_start: bool


@dataclass(slots=True)
class DiscoveredService:
    name: str
    directory: Path
    run_script: Path
    manifest: PluginManifest | None = None


@dataclass(slots=True)
class ManagedServiceRuntime:
    name: str
    directory: Path
    run_script: Path
    port: int
    base_url: str
    process: subprocess.Popen[Any]
    manifest: PluginManifest | None = None
    openapi_cache: dict[str, Any] | None = None


ACTIVE_SERVICES: dict[str, ManagedServiceRuntime] = {}


def _normalize_manifest_text(value: object, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _normalize_manifest_optional_path(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if text.startswith("/") else f"/{text}"


def _normalize_manifest_path(value: object, default: str) -> str:
    normalized = _normalize_manifest_optional_path(value)
    return normalized or default


def _normalize_manifest_start_command(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, (list, tuple)):
        return [part for item in value if (part := str(item).strip())]
    stripped = str(value).strip()
    return [stripped] if stripped else []


def _normalize_manifest_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_manifest_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _load_manifest(service_dir: Path) -> PluginManifest | None:
    manifest_path = service_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read manifest from %s: %s", manifest_path, exc)
        return None
    return PluginManifest(
        plugin_name=_normalize_manifest_text(data.get("plugin_name"), service_dir.name),
        version=_normalize_manifest_text(data.get("version"), "0.0.0"),
        runtime=_normalize_manifest_text(data.get("runtime"), "unknown"),
        start_command=_normalize_manifest_start_command(data.get("start_command")),
        health_path=_normalize_manifest_path(data.get("health_path"), "/health"),
        openapi_path=_normalize_manifest_optional_path(data.get("openapi_path")),
        startup_timeout_seconds=_normalize_manifest_float(
            data.get("startup_timeout_seconds"),
            READINESS_TIMEOUT_SECONDS,
        ),
        auto_start=_normalize_manifest_bool(data.get("auto_start"), True),
    )


def discover_services(services_root: Path = DEFAULT_SERVICES_DIR) -> list[DiscoveredService]:
    if not services_root.exists():
        return []

    discovered: list[DiscoveredService] = []
    for service_dir in sorted(services_root.iterdir(), key=lambda path: path.name):
        if not service_dir.is_dir():
            continue
        manifest = _load_manifest(service_dir)
        run_script = service_dir / "run.sh"
        if manifest is not None or run_script.is_file():
            discovered.append(
                DiscoveredService(
                    name=manifest.plugin_name if manifest else service_dir.name,
                    directory=service_dir,
                    run_script=run_script,
                    manifest=manifest,
                )
            )
    return discovered


def allocate_free_port(start: int = START_PORT) -> int:
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                port += 1
                if port > 65535:
                    raise RuntimeError("No free TCP ports available in the requested range.")
                continue
        return port


def _build_openapi_ref(service_name: str, schema_name: str) -> str:
    return f"#/components/schemas/{service_name}_{schema_name}"


def rewrite_schema_refs(payload: Any, service_name: str) -> Any:
    if isinstance(payload, dict):
        rewritten: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "$ref" and isinstance(value, str):
                schema_prefix = "#/components/schemas/"
                if value.startswith(schema_prefix):
                    schema_name = value.removeprefix(schema_prefix)
                    rewritten[key] = _build_openapi_ref(service_name, schema_name)
                    continue
            rewritten[key] = rewrite_schema_refs(value, service_name)
        return rewritten
    if isinstance(payload, list):
        return [rewrite_schema_refs(item, service_name) for item in payload]
    return payload


def merge_openapi_documents(service_documents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Process Manager Gateway", "version": "1.0.0"},
        "paths": {},
        "components": {"schemas": {}},
        "tags": [],
    }
    seen_tags: set[str] = set()

    for service_name, document in sorted(service_documents.items()):
        document_paths = rewrite_schema_refs(copy.deepcopy(document.get("paths", {})), service_name)
        document_paths = to_public_openapi_paths(document_paths, service_name)
        for path_name, path_item in document_paths.items():
            if path_name in merged["paths"]:
                logger.warning("Duplicate OpenAPI path %s from service %s overwrote a previous path", path_name, service_name)
            path_prefix = path_name.strip("/").replace("/", "_").replace("-", "_") or "path"
            for method, operation in path_item.items():
                if method in ("get", "post", "put", "patch", "delete", "head", "options") and isinstance(operation, dict):
                    operation["operationId"] = f"{path_prefix}_{method}"
            merged["paths"][path_name] = path_item

        document_schemas = copy.deepcopy(document.get("components", {}).get("schemas", {}))
        for schema_name, schema in document_schemas.items():
            merged["components"]["schemas"][f"{service_name}_{schema_name}"] = rewrite_schema_refs(
                schema, service_name
            )

        for tag in document.get("tags", []):
            tag_name = tag.get("name")
            if not isinstance(tag_name, str) or tag_name in seen_tags:
                continue
            merged["tags"].append(copy.deepcopy(tag))
            seen_tags.add(tag_name)

    if not merged["components"]["schemas"]:
        merged.pop("components")
    if not merged["tags"]:
        merged.pop("tags")
    return merged


async def fetch_service_openapi_documents(
    services: dict[str, ManagedServiceRuntime],
) -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        coroutines = [
            _fetch_single_service_openapi(client=client, service_name=name, service=service)
            for name, service in sorted(services.items())
        ]
        results = await asyncio.gather(*coroutines)

    documents: dict[str, dict[str, Any]] = {}
    for service_name, document in results:
        if document is not None:
            documents[service_name] = document
    return documents


async def _fetch_single_service_openapi(
    *,
    client: httpx.AsyncClient,
    service_name: str,
    service: ManagedServiceRuntime,
) -> tuple[str, dict[str, Any] | None]:
    if service.process.poll() is not None:
        logger.warning("Skipping OpenAPI fetch for service %s because the process is not running", service_name)
        return service_name, None

    openapi_path = service_openapi_path(service)
    if openapi_path is None:
        return service_name, None

    try:
        response = await client.get(f"{service.base_url}{openapi_path}")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch OpenAPI from service %s: %s", service_name, exc)
        return service_name, None

    document = response.json()
    service.openapi_cache = document
    return service_name, document


async def wait_for_service_ready(
    *,
    process: subprocess.Popen[Any],
    base_url: str,
    health_path: str = "/health",
    timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    probe_url = f"{base_url}{health_path}"

    async with httpx.AsyncClient(timeout=1.0) as client:
        while loop.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Service process exited before readiness probe succeeded: {base_url}")
            try:
                response = await client.get(probe_url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)

    raise TimeoutError(f"Service did not become ready within {timeout_seconds:.1f}s: {base_url}")


def build_start_command(service: DiscoveredService, port: int) -> list[str]:
    if service.manifest and service.manifest.start_command:
        return [
            part.replace("${PORT}", str(port)) for part in service.manifest.start_command
        ]
    return ["bash", str(service.run_script)]


def service_health_path(service: DiscoveredService | ManagedServiceRuntime) -> str:
    manifest = getattr(service, "manifest", None)
    return manifest.health_path if manifest is not None else "/health"


def service_openapi_path(service: DiscoveredService | ManagedServiceRuntime) -> str | None:
    manifest = getattr(service, "manifest", None)
    if manifest is None:
        return "/openapi.json"
    return manifest.openapi_path


def service_startup_timeout_seconds(
    service: DiscoveredService | ManagedServiceRuntime,
    default: float,
) -> float:
    manifest = getattr(service, "manifest", None)
    return manifest.startup_timeout_seconds if manifest is not None else default


async def launch_services(
    *,
    services_root: Path,
    registry: dict[str, ManagedServiceRuntime],
    start_port: int = START_PORT,
    readiness_timeout: float = READINESS_TIMEOUT_SECONDS,
) -> None:
    next_port = start_port
    for service in discover_services(services_root):
        manifest = service.manifest
        if manifest and not manifest.auto_start:
            logger.info("Skipping auto-start for plugin %s (auto_start=false)", service.name)
            continue

        port = allocate_free_port(next_port)
        next_port = port + 1
        env = {
            **os.environ,
            "SERVICE_PORT": str(port),
            "SERVICE_PYTHON": sys.executable,
        }
        cmd = build_start_command(service, port)
        process = subprocess.Popen(
            cmd,
            cwd=service.directory,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        health_path = service_health_path(service)
        timeout = service_startup_timeout_seconds(service, readiness_timeout)
        runtime = ManagedServiceRuntime(
            name=service.name,
            directory=service.directory,
            run_script=service.run_script,
            port=port,
            base_url=f"http://127.0.0.1:{port}",
            process=process,
            manifest=manifest,
        )
        registry[service.name] = runtime
        logger.info(
            "Starting plugin %s (%s) on http://127.0.0.1:%s",
            service.name,
            manifest.runtime if manifest else "unknown",
            port,
        )
        try:
            await wait_for_service_ready(
                process=process,
                base_url=runtime.base_url,
                health_path=health_path,
                timeout_seconds=timeout,
            )
        except Exception:
            logger.error("Plugin %s failed to start, shutting down all services", service.name)
            await shutdown_services(registry)
            raise

        openapi_path = service_openapi_path(service)
        if openapi_path:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{runtime.base_url}{openapi_path}")
                    if resp.status_code == 200:
                        runtime.openapi_cache = resp.json()
            except Exception as exc:
                logger.warning("Failed to fetch OpenAPI for plugin %s: %s", service.name, exc)

        logger.info(
            "Started plugin %s (%s) on http://127.0.0.1:%s (pid=%s)",
            service.name,
            manifest.runtime if manifest else "unknown",
            port,
            process.pid,
        )


async def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        await asyncio.to_thread(process.wait, PROCESS_SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            await asyncio.to_thread(process.wait, PROCESS_SHUTDOWN_TIMEOUT_SECONDS)


async def shutdown_services(registry: dict[str, ManagedServiceRuntime]) -> None:
    services = list(registry.values())
    for service in services:
        await terminate_process(service.process)
    registry.clear()


async def _close_upstream_response(upstream_response: httpx.Response) -> None:
    await upstream_response.aclose()


def create_app(
    *,
    services_root: Path = DEFAULT_SERVICES_DIR,
    registry: dict[str, ManagedServiceRuntime] | None = None,
    start_port: int = START_PORT,
    readiness_timeout: float = READINESS_TIMEOUT_SECONDS,
) -> FastAPI:
    active_services = ACTIVE_SERVICES if registry is None else registry

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.active_services = active_services
        app.state.services_root = services_root
        app.state.proxy_http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        if active_services:
            await shutdown_services(active_services)
        await launch_services(
            services_root=services_root,
            registry=active_services,
            start_port=start_port,
            readiness_timeout=readiness_timeout,
        )
        try:
            yield
        finally:
            await app.state.proxy_http_client.aclose()
            await shutdown_services(active_services)

    app = FastAPI(
        title="Process Manager Gateway",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/health", tags=["system"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "plugin-gateway"})

    @app.get("/services", include_in_schema=False)
    async def list_services(request: Request) -> JSONResponse:
        services: dict[str, ManagedServiceRuntime] = request.app.state.active_services
        items = [
            {
                "name": name,
                "status": "running" if svc.process.poll() is None else "stopped",
                "mount_prefix": f"{PUBLIC_PLUGIN_PREFIX}/{name}",
            }
            for name, svc in sorted(services.items())
        ]
        return JSONResponse({"services": items})

    @app.get("/ready", tags=["system"])
    async def ready() -> JSONResponse:
        configured_services_root = getattr(app.state, "services_root", services_root)
        if not Path(configured_services_root).exists():
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": "plugin-gateway",
                    "detail": f"Services root is missing: {configured_services_root}",
                },
            )
        return JSONResponse({"status": "ready", "service": "plugin-gateway"})

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{app.title} Docs",
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_document(request: Request) -> JSONResponse:
        services: dict[str, ManagedServiceRuntime] = request.app.state.active_services
        documents = await fetch_service_openapi_documents(services)
        return JSONResponse(merge_openapi_documents(documents))

    @app.api_route(
        f"{PUBLIC_PLUGIN_PREFIX}/{{service_name}}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    @app.api_route(
        f"{PUBLIC_PLUGIN_PREFIX}/{{service_name}}/{{path:path}}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def proxy_request(service_name: str, request: Request, path: str = "") -> StreamingResponse:
        del path
        services: dict[str, ManagedServiceRuntime] = request.app.state.active_services
        service = services.get(service_name)
        if service is None:
            raise HTTPException(status_code=404, detail=f"Unknown service: {service_name}")
        if service.process.poll() is not None:
            raise HTTPException(status_code=502, detail=f"Service is unavailable: {service_name}")

        client: httpx.AsyncClient = request.app.state.proxy_http_client
        upstream_url = f"{service.base_url}{to_internal_plugin_path(request.url.path, service_name)}"
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            upstream_request = client.build_request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                params=request.query_params.multi_items(),
                content=await request.body(),
                cookies=request.cookies,
            )
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            logger.warning("Proxy request to service %s failed: %s", service_name, exc)
            raise HTTPException(status_code=502, detail=f"Bad Gateway for service: {service_name}") from exc

        response_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return StreamingResponse(
            upstream_response.aiter_raw(),
            status_code=upstream_response.status_code,
            headers=response_headers,
            background=BackgroundTask(_close_upstream_response, upstream_response),
        )

    return app


app = create_app()
