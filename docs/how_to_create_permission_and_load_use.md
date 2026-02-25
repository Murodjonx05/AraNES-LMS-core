# How To Use Permissions (RBAC)

## What Is Checked

Права хранятся в двух местах:

- `roles.permissions`
- `users.permissions`

Итоговые (effective) права:

```text
effective = role.permissions + user.permissions
```

`user.permissions` имеет приоритет (override).

For example:

```json
role.permissions = { "i18n_can_patch_large": false }
user.permissions = { "i18n_can_patch_large": true }
effective         = { "i18n_can_patch_large": true }
```

## Quick Example: Create + Register New Permission

Ниже минимальный пример, если хочешь добавить новый permission для своего модуля.

### 1. Create permission key + defaults

For example (`src/course/permission.py`):

```python
COURSE_CAN_CREATE = "course_can_create"

COURSE_ROLE_PERMISSION_DEFAULTS = {
    "SuperAdmin": {"course_can_create": True},
    "Admin": {"course_can_create": True},
    "Teacher": {"course_can_create": True},
    "Student": {"course_can_create": False},
    "User": {"course_can_create": False},
    "Guest": {"course_can_create": False},
}
```

### 2. Register in `RBAC_SERVICE`

For example (`src/user_role/bootstrap.py`):

```python
from src.course.permission import COURSE_ROLE_PERMISSION_DEFAULTS

RBAC_SERVICE.register_role_permission_defaults(COURSE_ROLE_PERMISSION_DEFAULTS)
```

После перезапуска приложения новый key будет добавлен в `roles.permissions`, если его там еще нет.

## Two Ways To Check Permissions

### 1. Static Check (`require_permission`)

Используй, когда право заранее известно.

For example:

```python
from fastapi import Depends
from src.user_role.middlewares import require_permission
from src.user_role.permission import RBAC_CAN_MANAGE_PERMISSIONS

@router.patch(
    "/roles/{role_id}/permissions",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def patch_role_permissions(...):
    ...
```

### 2. Dynamic Check (`ensure_permission`)

Используй, когда право зависит от логики внутри endpoint.

For example (`PUT /api/v1/i18n/large`):

```python
user, role = user_role_pair

if item is None:
    ensure_permission(user, role, I18N_CAN_CREATE_LARGE)
else:
    ensure_permission(user, role, I18N_CAN_PATCH_LARGE)
```

## i18n Create/Patch Matrix

- `create=True`, `patch=True`
  - can create and patch
- `create=True`, `patch=False`
  - can create only
- `create=False`, `patch=True`
  - can patch existing only
- `create=False`, `patch=False`
  - no access

For example:

```json
{
  "i18n_can_create_large": false,
  "i18n_can_patch_large": true
}
```

Behavior:

- `PUT /api/v1/i18n/large` for new `key1/key2` -> `403`
- `PUT /api/v1/i18n/large` for existing `key1/key2` -> `200`

## How To Grant Permission

### Grant To Role

Endpoint:

- `PATCH /api/v1/rbac/roles/{role_id}/permissions`

For example:

```json
{
  "i18n_can_create_small": true,
  "i18n_can_patch_small": true
}
```

### Grant To User (Override)

Endpoint:

- `PATCH /api/v1/rbac/users/{user_id}/permissions`

For example:

```json
{
  "i18n_can_create_large": true
}
```

## How To Test Quickly

1. Login as a user
2. Grant permission via RBAC endpoint (role or user)
3. Call protected endpoint
4. Check response:
   - `200` -> permission works
   - `403 Missing permission: ...` -> permission missing

## Related Docs

- `docs/doc.md` (overview)
- `docs/how_to_create_permission_and_load.md` (create + load/seed)