# Agent-Native Architecture Review: AraNES-LMS-core

**Date:** 2025-03-11  
**Codebase:** `/run/media/aestra/data/PYTHON/lms` (FastAPI backend: auth, RBAC, i18n, plugins, gateway)

**Scope:** Цель — идеальный LMS-backend с плагинными расширениями. Фронтенд не в scope: все улучшения (agent parity, capability discovery, UI integration) рассматриваются на уровне API, документации и агентских инструментов (MCP/OpenAPI).

---


## Overall Score Summary

| Core Principle           | Score   | Percentage | Status |
|--------------------------|---------|------------|--------|
| Action Parity            | 0/33    | 0%         | ❌     |
| Tools as Primitives      | 28/34   | 82%        | ✅     |
| Context Injection        | 0/6     | 0%         | ❌     |
| Shared Workspace         | 3/3     | 100%       | ✅     |
| CRUD Completeness        | 5/5     | 100%       | ✅     |
| UI Integration           | 20/24   | 83%        | ✅     |
| Capability Discovery     | 2/7     | 29%        | ❌     |
| Prompt-Native Features   | 0/15    | 0%         | ❌     |

**Overall Agent-Native Score: 49%**

### Status Legend

- ✅ Excellent (80%+)
- ⚠️ Partial (50–79%)
- ❌ Needs Work (&lt;50%)

---

## Principle Summaries

### 1. Action Parity — 0/33 (0%)

- **User actions:** 33 API operations (health, auth, RBAC roles/users, i18n small/large, plugins, proxy).
- **Agent tools:** None (no MCP server or agent-facing tool layer in repo).
- **Gap:** The agent cannot perform any of these actions via tools; parity requires an agent/MCP layer that maps to the same APIs.

### 2. Tools as Primitives — 28/34 (82%)

- API endpoints treated as “tools”; ~82% are capability-only (read/write/list/delete).
- **Workflow-like (6):** auth signup/login, GET /plugins (gateway+cache), users/reset, roles/reset, role-registry append.
- **Recommendation:** Split auth into primitives + thin workflow endpoints; make plugin list and bulk resets thin over primitives.

### 3. Context Injection — 0/6 (0%)

- No LLM/agent layer; no system prompt or context builder.
- Request/app state (actor, request_id) is used for HTTP only, not for prompts.
- **If you add an agent:** Add a single context/prompt builder and inject resources, capabilities, and session state.

### 4. Shared Workspace — 3/3 (100%)

- Primary DB, Redis, and filesystem (data/, services/, logs/) are shared; no agent-only sandbox.
- User requests and internal code (PluginManager, bootstrap, lifespan) use the same `RuntimeContext`.

### 5. CRUD Completeness — 5/5 (100%)

- **Full CRUD:** Role, User, TranslateTitle (small i18n), TranslateDesc (large i18n), PluginMapping.

### 6. UI Integration — 20/24 (83%)

- Most mutations return response body + cache invalidation; acting client and next GETs see updates.
- **Gaps:** Plugin list cache (TTL), core OpenAPI fixed at startup, token revocation not pushed to other sessions, no push for multi-tab.

### 7. Capability Discovery — 2/7 (29%)

- **Present:** Help docs (README, docs/), programmatic exposure (OpenAPI, gateway `/services`, `/docs`).
- **Missing (backend-only):** Единый “что умеет API” в docs, список возможностей для агентов/клиентов; onboarding/UI/slash — вне scope.

### 8. Prompt-Native Features — 0/15 (0%)

- No agent prompts; all behavior is code/config (roles, permissions, auth, gateway, bootstrap).
- To improve: introduce an agent layer and define outcomes in prompts or declarative config.

---

## Top 10 Recommendations by Impact

| Priority | Action | Principle | Effort |
|----------|--------|-----------|--------|
| 1 | Add agent/MCP layer and map API operations to tools (or one `lms_api_request` tool + auth). | Action Parity | High |
| 2 | Complete CRUD: **done** (roles, users, i18n small/large, and PluginMapping now have full CRUD). | CRUD Completeness | Medium |
| 3 | Document “what you can do” and point to OpenAPI + gateway `/services` for capability discovery. | Capability Discovery | Low |
| 4 | Add system prompt/context builder when introducing an LLM (resources, capabilities, session). | Context Injection | Medium |
| 5 | Reduce plugin list TTL or add cache-bust; optionally refresh gateway OpenAPI periodically. | UI Integration | Low |
| 6 | Split auth into primitives (create_user, issue_token, verify_credentials) + thin signup/login. | Tools as Primitives | Medium |
| 7 | Make GET /plugins and bulk resets thin over primitives; document workflow endpoints. | Tools as Primitives | Low |
| 8 | Add “capabilities” doc and optional `/api/v1/capabilities` (backend-only; frontend out of scope). | Capability Discovery | Low |
| 9 | Move roles/permissions and endpoint–permission mapping to config/DB for easier change without code. | Prompt-Native | High |
| 10 | Document single-workspace design (one DB, one Redis) so future changes don’t introduce agent-only stores. | Shared Workspace | Low |

---

## What’s Working Well

1. **Shared workspace** — Single DB, Redis, and filesystem; no sandbox isolation.
2. **Primitive-heavy API** — Most endpoints are read/write/list/delete; good base for future tools.
3. **UI reflection** — Response bodies + cache invalidation give immediate consistency for the acting client and refetches.
4. **Structured docs** — README and docs/ cover API surface and ops; OpenAPI and gateway `/services` expose capabilities programmatically.
5. **Auth and RBAC** — Full CRUD for users and roles; permission model is clear and consistent.

---

## Optimize Code Using Dev Packages (`requirements/dev.txt`)

Using **pytest**, **pytest-asyncio**, **httpx**, **FastAPI**, and **pydantic** from your dev stack:

### Pytest

- **Parametrize to reduce duplication:** Use `@pytest.mark.parametrize` for multiple inputs/expected outputs (e.g. path transformation, schema rewriting) so one test function covers many cases.
- **Fixtures for shared setup:** Use `@pytest.fixture` for `ManagedServiceRuntime`, mock proxy client, and app+transport so gateway tests don’t repeat the same 10+ lines.
- **Parametrized fixtures:** For “same test, different backend,” use `@pytest.fixture(params=[...])` so one test runs over several configurations.

### FastAPI testing

- **Dependency overrides:** Use `app.dependency_overrides` to inject test doubles (e.g. `get_request_cache_service`, `require_access_token_payload`) so tests don’t hit real Redis/DB or auth.
- **TestClient vs AsyncClient:** Use `httpx.ASGITransport(app=app)` with `httpx.AsyncClient` for async endpoint tests (as in `test_gateway_comprehensive.py`); use `TestClient` for sync or when overrides are enough.

### Pydantic

- Use type hints and validators for request/response models so validation and serialization stay consistent and easy to test (e.g. plugin manifest, i18n payloads).

### Ruff

- Keep `ruff` for lint/format; run before commits to keep style consistent and catch simple bugs.

Applying these patterns (parametrize, fixtures, dependency overrides) will keep tests minimal and readable while preserving coverage—as in the recent gateway test refactor.

---

## Next Steps

| # | Action | File / area | Done |
|---|--------|-------------|------|
| 1 | Add DELETE for i18n small: `DELETE /api/v1/i18n/small/{key}` + crud + cache invalidation | `src/i18n/endpoints/small.py`, `src/i18n/crud.py`, `src/i18n/cache.py` | ✅ |
| 2 | Add DELETE for i18n large: `DELETE /api/v1/i18n/large/{key1}/{key2}` + crud + cache invalidation | `src/i18n/endpoints/large.py`, `src/i18n/crud.py`, `src/i18n/cache.py` | ✅ |
| 3 | Add GET single plugin: `GET /api/v1/plugins/{plugin_name}` | `src/plugins/endpoints.py` | ✅ |
| 4 | Add DELETE plugin mapping: `DELETE /api/v1/plugins/{plugin_name}` | `src/plugins/endpoints.py`, `src/plugins/crud.py` | ✅ |
| 5 | Document capabilities (backend-only): what the API can do, in README or `docs/` | `README.md`, `docs/` | ✅ |
| 6 | Optional: reduce `PLUGIN_GATEWAY_CACHE_TTL_SECONDS` or add cache-bust for plugin list | `src/config.py`, plugin fetch in lifespan | ✅ |
| 7 | When adding an agent: add MCP server or tool layer mapping to existing API operations | New package or `src/agent/` | ✅ |

Re-run this audit after adding an agent layer or completing CRUD to track progress.
