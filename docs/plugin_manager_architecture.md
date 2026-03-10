# Plugin manager architecture

This document describes the plugin and gateway design for the LMS core app. Plugins allow optional features or external services to be managed and (when using the gateway) exposed under a common prefix with consistent discovery and observability.

## Goals

- Expose a **management API** in the core: list plugins and enable/disable them (when using DB-backed mappings).
- When **plugin gateway** is configured, the core fetches the list of running services from the gateway and does not support PATCH (gateway-managed plugins are read-only from the core).
- Support **external demo services** (Node, Flask, FastAPI) via a separate gateway process that discovers services by manifest, starts them as subprocesses, and proxies requests under `/plg/{service_name}/...`.

## Core: Plugin API

- **Prefix**: `/api/v1/plugins`
- **Auth**: All plugin endpoints require a valid Bearer token and the permission `rbac_can_manage_permissions`.
- **Endpoints**:
  - `GET /api/v1/plugins` — list plugin mappings. If `PLUGIN_GATEWAY_URL` is set, the list is fetched from the gateway's `GET /services`; otherwise it is read from the `plugin_mappings` table.
  - `PATCH /api/v1/plugins/{plugin_name}` — set `enabled` for a plugin. Only available when **not** using the gateway (otherwise returns 405).

## Database: plugin_mappings

When the core is used **without** a gateway, plugin state is stored in the table `plugin_mappings`:

- `plugin_name`, `service_name`, `mount_prefix` — identity and mount path
- `enabled` — whether the plugin is enabled

Migrations: see `migrations/versions/` for the schema.

## Plugin gateway (optional)

The **gateway server** (`gateway_server/gateway.py`) is a separate FastAPI process that:

1. **Discovers** services under a configurable directory (default `services/`). Each service is a folder with:
   - `manifest.json` — `plugin_name`, `version`, `runtime`, `start_command`, `health_path`, `openapi_path`, `startup_timeout_seconds`, `auto_start`
   - `run.sh` — script to start the service (or use `start_command` from manifest)
2. **Starts** services as subprocesses on allocated ports (from a start port, e.g. 10000).
3. **Exposes**:
   - `GET /services` — list of services with `name`, `mount_prefix`, `status` (e.g. `running`)
   - `GET /openapi.json` — merged OpenAPI document from all running services (paths under `/plg/{service_name}/...`)
   - `GET /plg/{service_name}/...` — proxy to the corresponding backend (and forwards auth/request-id headers)
4. **Stops** services on gateway shutdown.

The core app does **not** proxy plugin traffic itself; when the frontend or a client calls plugin endpoints, they call the gateway URL (e.g. `http://plugins:8001/plg/demo_fastapi/...`). The core only uses the gateway to **list** plugins when `PLUGIN_GATEWAY_URL` is set.

## Configuration (core)

- `PLUGIN_MANAGER_ENABLED` — enable plugin manager (default `True`).
- `PLUGIN_GATEWAY_URL` — if set, `GET /api/v1/plugins` uses the gateway's `/services` and PATCH is disabled.
- `PLUGIN_GATEWAY_CACHE_TTL_SECONDS` — short-lived cache for the gateway-backed plugin list in the core app. `0` disables cache.
- `PLUGIN_START_PORT`, `PLUGIN_READINESS_TIMEOUT`, `PLUGIN_SERVICES_DIR` — used by the gateway, not the core (core only needs `PLUGIN_GATEWAY_URL` for discovery).

See [Configuration Reference](./configuration.md) for full env list.

## Demo services

Under `services/`:

- `demo_fastapi/` — FastAPI app with `manifest.json` and `run.sh`
- `demo_flask/` — Flask app
- `demo_node/` — Node server

Each can be run by the gateway when present in the gateway's services directory.

## File layout

- `src/plugins/` — plugin API in the core:
  - `models.py` — `PluginMapping` SQLAlchemy model
  - `crud.py` — list/set enabled for DB mappings
  - `schemas.py` — `PluginMappingRead`, `PluginEnabledPatch`
  - `endpoints.py` — `GET /plugins`, `PATCH /plugins/{plugin_name}` (with gateway vs DB logic)
  - `route.py` — mounts plugin router under `/api/v1`
- `gateway_server/gateway.py` — FastAPI app: discovery, process management, `/services`, `/openapi.json`, `/plg/...` proxy
- `services/*/` — demo plugin services with manifest and run script

## Integration tests

- `tests/integration/test_plugin_gateway.py` — gateway discovery and proxy
- `tests/integration/test_plugin_lifecycle.py` — core API and DB-backed enable/disable
- `tests/state/test_plugin_state_transitions.py` — plugin state transitions
- `tests/gateway_server/test_gateway.py` — gateway unit tests
