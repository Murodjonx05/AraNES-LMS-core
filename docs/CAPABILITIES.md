# API Capabilities (Backend)

What the LMS backend and plugin gateway can do. For full request/response shapes see OpenAPI: `/openapi.json` (core) and gateway `GET /openapi.json` when `PLUGIN_GATEWAY_URL` is set.

## System

| Capability        | Method + Path   | Description                    |
|-------------------|-----------------|--------------------------------|
| Health check      | `GET /health`   | Process health                 |
| Readiness         | `GET /ready`    | DB (and optional Redis) ready  |

## Auth

| Capability     | Method + Path                    | Description                    |
|----------------|----------------------------------|--------------------------------|
| Sign up        | `POST /api/v1/auth/signup`       | Register and get access token  |
| Log in         | `POST /api/v1/auth/login`        | Get access token               |
| Revoke token   | `POST /api/v1/auth/reset`        | Revoke current token           |
| Current user   | `GET /api/v1/auth/me`            | Caller identity and permissions|

Use `Authorization: Bearer <access_token>` for protected routes.

## RBAC

| Capability       | Method + Path                                           |
|------------------|----------------------------------------------------------|
| List roles       | `GET /api/v1/rbac/roles`                                 |
| Get role         | `GET /api/v1/rbac/roles/{role_id}`                      |
| Create role      | `POST /api/v1/rbac/roles`                               |
| Update role      | `PATCH /api/v1/rbac/roles/{role_id}`                    |
| Delete role      | `DELETE /api/v1/rbac/roles/{role_id}`                  |
| Patch role perms | `PATCH /api/v1/rbac/roles/{role_id}/permissions`        |
| Reset roles      | `POST /api/v1/rbac/roles/reset`                         |
| Role registry    | `POST /api/v1/rbac/roles/role-registry/`                |
| List users       | `GET /api/v1/rbac/users`                                |
| Get user         | `GET /api/v1/rbac/users/{user_id}`                      |
| Create user      | `POST /api/v1/rbac/users`                               |
| Update user      | `PATCH /api/v1/rbac/users/{user_id}`                    |
| Set password     | `PUT /api/v1/rbac/users/{user_id}/password`             |
| Delete user      | `DELETE /api/v1/rbac/users/{user_id}`                   |
| Patch user perms | `PATCH /api/v1/rbac/users/{user_id}/permissions`        |
| Reset users      | `POST /api/v1/rbac/users/reset`                         |

Requires `rbac_can_manage_permissions` for mutations; read permissions are role-specific.

## i18n

| Capability     | Method + Path                              |
|----------------|--------------------------------------------|
| List small     | `GET /api/v1/i18n/small`                   |
| Get small      | `GET /api/v1/i18n/small/{key}`             |
| Upsert small   | `PUT /api/v1/i18n/small`                   |
| Delete small   | `DELETE /api/v1/i18n/small/{key}`         |
| List large     | `GET /api/v1/i18n/large`                   |
| Get large      | `GET /api/v1/i18n/large/{key1}/{key2}`    |
| Upsert large   | `PUT /api/v1/i18n/large`                   |
| Delete large   | `DELETE /api/v1/i18n/large/{key1}/{key2}`  |

Permissions: `i18n_can_read_small`, `i18n_can_create_small`, `i18n_can_patch_small` (and `_large` analogues).

## Plugins

| Capability       | Method + Path                          | Notes                                      |
|-------------------|----------------------------------------|--------------------------------------------|
| List plugins      | `GET /api/v1/plugins`                  | From gateway if `PLUGIN_GATEWAY_URL` set   |
| Get plugin        | `GET /api/v1/plugins/{plugin_name}`    | Single mapping or gateway service          |
| Create mapping    | `POST /api/v1/plugins`                 | DB mode only                               |
| Enable/disable    | `PATCH /api/v1/plugins/{plugin_name}` | DB mode only                               |
| Delete mapping    | `DELETE /api/v1/plugins/{plugin_name}`| DB mode only                               |

Requires `rbac_can_manage_permissions`. When gateway is used, list/get come from gateway `/services` (cached); create/patch/delete return 405.

## Plugin gateway (standalone)

When running the gateway server (e.g. Docker `plugins` service):

| Capability   | Method + Path     | Description              |
|--------------|-------------------|--------------------------|
| Health       | `GET /health`     | Gateway health           |
| Readiness    | `GET /ready`      | Gateway ready            |
| List services| `GET /services`   | Managed plugin processes |
| OpenAPI      | `GET /openapi.json` | Merged plugin schemas  |
| Proxy        | `* /plg/{name}/{path:path}` | Forward to plugin |

## Discovery

- **OpenAPI (core):** `GET /openapi.json` — full core API schema.
- **OpenAPI (gateway):** When `PLUGIN_GATEWAY_URL` is set, core may merge gateway schema at startup; gateway exposes `GET /openapi.json` and `GET /services` for plugin discovery.
