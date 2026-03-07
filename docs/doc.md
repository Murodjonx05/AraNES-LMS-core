# Docs Index

## Documentation Links

- [How To Use Permissions (RBAC)](./how_to_create_permission_and_load_use.md)
  - Как проверять права в endpoint'ах
  - `require_permission(...)` vs `ensure_permission(...)`
  - Как выдать права роли/пользователю
  - Примеры для i18n `small/large`
- [How To Create Translates For Keys (i18n)](./how_to_create_translate_for_keys.md)
  - Как создавать переводы по key (`...title`)
  - Как регистрировать их в i18n registry
  - Как они загружаются в БД через i18n bootstrap
- [Configuration Reference](./configuration.md)
  - Основные env-переменные
  - Redis / rate limit / bootstrap
  - Logging / profiling toggles
- [Operability Notes](./operability.md)
  - `/health` и `/ready`
  - request/audit logging
  - request id и Redis heartbeat
- [Cache And Revocation](./cache_and_revocation.md)
  - i18n/RBAC Redis cache
  - auth token revocation
  - fallback behaviour

## Current Active Permissions

### RBAC

- `rbac_can_manage_permissions`
- `rbac_roles_read`
- `rbac_roles_create`
- `rbac_roles_update`
- `rbac_roles_delete`
- `rbac_users_read`
- `rbac_users_create`
- `rbac_users_manage`

### i18n

- `i18n_can_read_small`
- `i18n_can_create_small`
- `i18n_can_patch_small`
- `i18n_can_read_large`
- `i18n_can_create_large`
- `i18n_can_patch_large`

## Quick Start (Very Short)

1. Создай permission key в `src/<module>/permission.py`
2. Добавь default права по ролям
3. Зарегистрируй defaults в `RBAC_SERVICE` (`src/user_role/bootstrap.py`)
4. Используй в endpoint:
   - статично: `Depends(require_permission(...))`
   - динамически: `ensure_permission(user, role, ...)`

## Resources

- Main usage guide: [How To Use Permissions (RBAC)](./how_to_create_permission_and_load_use.md)
- i18n keys/translates guide: [How To Create Translates For Keys (i18n)](./how_to_create_translate_for_keys.md)
- Env/runtime guide: [Configuration Reference](./configuration.md)
- Runtime/cache/auth notes: [Cache And Revocation](./cache_and_revocation.md)
- Operations guide: [Operability Notes](./operability.md)
