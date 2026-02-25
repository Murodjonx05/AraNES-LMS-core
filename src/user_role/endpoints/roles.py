from fastapi import APIRouter, Depends, HTTPException

from src.database import DbSession
from src.user_role.crud import (
    list_roles as crud_list_roles,
    patch_role_permissions as crud_patch_role_permissions,
    reset_role_permissions as crud_reset_role_permissions,
)
from src.user_role.endpoints.serializers import serialize_role
from src.user_role.exceptions import RoleNotFoundError, SuperAdminRoleImmutableError
from src.user_role.middlewares import require_permission
from src.user_role.permission import RBAC_CAN_MANAGE_PERMISSIONS
from src.user_role.schemas import PermissionPatchSchema

roles_router = APIRouter(prefix="/roles", tags=["rbac:roles"])


@roles_router.get("")
async def list_roles(session: DbSession):
    """
    Return a list of all roles as dictionaries.
    """
    roles = await crud_list_roles(session)
    return [serialize_role(role) for role in roles]


@roles_router.patch(
    "/{role_id}/permissions",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def patch_role_permissions(
    role_id: int,
    permissions: PermissionPatchSchema,
    session: DbSession,
):
    """
    Update the permissions of a role, unless it's the SuperAdmin role.
    """
    try:
        updated_role = await crud_patch_role_permissions(
            session,
            role_id=role_id,
            permission_patch=permissions.root,
        )
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SuperAdminRoleImmutableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return serialize_role(updated_role)


@roles_router.post(
    "/reset",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def reset_role_permissions(session: DbSession):
    """
    Reset permissions for all roles except the SuperAdmin role.
    Returns the count of updated roles.
    """
    updated_count = await crud_reset_role_permissions(session)
    return {"updated": updated_count}
