# Future: Agent / MCP Layer

When adding an AI agent or automation layer, the backend should expose the same capabilities via tools so that **whatever a client can do via the API, an agent can do via tools** (action parity).

## Recommended approach

1. **New package or `src/agent/`**  
   Host MCP server or tool definitions in a dedicated module so the core API stays unchanged.

2. **Map existing API to tools**  
   Either:
   - **One generic tool:** e.g. `lms_api_request(method, path, body?, query?)` with auth (Bearer from context or service token), or
   - **Domain tools:** e.g. `list_roles`, `create_user`, `get_plugin`, etc., each calling the corresponding HTTP endpoint.

3. **Auth for agent calls**  
   Define how the agent gets credentials (e.g. service account, user-impersonation token) and pass them on each request (e.g. `Authorization: Bearer <token>`).

4. **Discovery**  
   Expose capability list and/or OpenAPI to the agent so it knows available operations. See [CAPABILITIES.md](./CAPABILITIES.md) and `/openapi.json`.

## Out of scope (for now)

- Frontend or chat UI.
- In-app “prompts” or slash commands (backend-only scope).

## References

- [AGENT_NATIVE_AUDIT_REPORT.md](./AGENT_NATIVE_AUDIT_REPORT.md) — current scores and recommendations.
- [CAPABILITIES.md](./CAPABILITIES.md) — what the API can do.
