from fastapi import APIRouter, HTTPException

from src.database import session_scope
from src.user_role.crud import (
    create_or_append_role_permissions_no_overwrite,
)
from src.user_role.exceptions import DuplicatePermissionKeysError
from src.user_role.schemas import RoleRegistrySchema

role_registry_router = APIRouter(prefix="/roles", tags=["rbac:roles"])


@role_registry_router.post("/role-registry/")
async def registry_roles_once_if_not_exist(payload: RoleRegistrySchema):
    """
    Create a role with the given name and permissions if it doesn't exist.
    If it exists, update its permissions.
    """
    async with session_scope() as session:
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

        return {
            "status": result.status,
            "role": result.role,
            "permissions": result.permissions,
        }
