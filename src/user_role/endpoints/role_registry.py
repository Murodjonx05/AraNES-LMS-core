from fastapi import APIRouter, Depends, HTTPException

from src.database import DbSession
from src.user_role.crud import (
    create_or_append_role_permissions_no_overwrite,
)
from src.user_role.exceptions import (
    DuplicatePermissionKeysError,
    InvalidPermissionPatchError,
    RoleNotFoundError,
)
from src.user_role.middlewares import require_permission
from src.user_role.permission import RBAC_CAN_MANAGE_PERMISSIONS
from src.user_role.schemas import RoleRegistrySchema

role_registry_router = APIRouter(prefix="/roles", tags=["rbac:roles"])


@role_registry_router.post(
    "/role-registry/",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def registry_roles_once_if_not_exist(payload: RoleRegistrySchema, session: DbSession):
    """
    Append permissions to an existing role without overwriting existing keys.
    Does not create a new role.
    """
    try:
        result = await create_or_append_role_permissions_no_overwrite(
            session,
            role_name=payload.name,
            permission_patch=payload.permissions,
        )
    except DuplicatePermissionKeysError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "duplicate_keys": exc.duplicate_keys,
            },
        ) from exc
    except InvalidPermissionPatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": result.status,
        "role": result.role,
        "permissions": result.permissions,
    }
