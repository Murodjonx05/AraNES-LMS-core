# Cache And Revocation

## Redis Cache Layers

Redis в проекте не является источником истины. Он используется как ускоряющий слой поверх БД и runtime state.

## i18n Cache

Кэшируются:

- `GET /api/v1/i18n/small`
- `GET /api/v1/i18n/small/{key}`
- `GET /api/v1/i18n/large`
- `GET /api/v1/i18n/large/{key1}/{key2}`

Write-path:

- после успешного `PUT` инвалидируются только соответствующие key/list cache entries

## RBAC Cache

Кэшируются:

- `GET /api/v1/rbac/roles`
- `GET /api/v1/rbac/roles/{role_id}`
- `GET /api/v1/rbac/users`
- `GET /api/v1/rbac/users/{user_id}`

Write-path:

- invalidate идёт точечно по role/user keys и соответствующим list keys

## Auth Revocation

Источник истины:

- таблица `auth_revoked_token_jtis`

Поверх неё используются:

- local in-process cache
- Redis shared cache

Это даёт:

- сохранение revoked tokens после рестарта
- общий revocation state между воркерами и инстансами

## Fallback Behaviour

Если Redis отключён или недоступен:

- i18n/RBAC read paths падают обратно на DB reads
- revocation продолжает работать через БД
- rate limit может использовать in-memory fallback
