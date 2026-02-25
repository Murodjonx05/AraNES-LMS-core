from fastapi import APIRouter, Depends, HTTPException

from src.database import DbSession
from src.user_role.crud import (
    list_users as crud_list_users,
    patch_user_permissions as crud_patch_user_permissions,
    reset_user_permissions as crud_reset_user_permissions,
)
from src.user_role.endpoints.serializers import serialize_user
from src.user_role.exceptions import UserNotFoundError
from src.user_role.middlewares import require_permission
from src.user_role.permission import RBAC_CAN_MANAGE_PERMISSIONS
from src.user_role.schemas import PermissionPatchSchema

users_router = APIRouter(prefix="/users", tags=["rbac:users"])


@users_router.get("")
async def list_users(session: DbSession):
    users = await crud_list_users(session)
    return [serialize_user(user) for user in users]


@users_router.patch(
    "/{user_id}/permissions",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def patch_user_permissions(
    user_id: int,
    permissions: PermissionPatchSchema,
    session: DbSession,
):
    try:
        updated_user = await crud_patch_user_permissions(
            session,
            user_id=user_id,
            permission_patch=permissions.root,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_user(updated_user)


@users_router.post(
    "/reset",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def reset_user_permissions(session: DbSession):
    count = await crud_reset_user_permissions(session)
    return {"updated": count}
