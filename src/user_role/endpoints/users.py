from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.auth.exceptions import UsernameAlreadyExistsError
from src.database import DbSession
from src.user_role.crud import (
    create_user_admin as crud_create_user_admin,
    delete_user_admin as crud_delete_user_admin,
    get_user_by_id as crud_get_user_by_id,
    list_users as crud_list_users,
    patch_user_permissions as crud_patch_user_permissions,
    reset_user_permissions as crud_reset_user_permissions,
    set_user_password_admin as crud_set_user_password_admin,
    update_user_admin as crud_update_user_admin,
)
from src.user_role.endpoints.serializers import serialize_user
from src.user_role.exceptions import (
    InvalidPermissionPatchError,
    RoleNotFoundError,
    SelfDeleteForbiddenError,
    UserNotFoundError,
)
from src.user_role.middlewares import require_permission
from src.user_role.permission import (
    RBAC_CAN_MANAGE_PERMISSIONS,
    RBAC_USERS_CREATE,
    RBAC_USERS_MANAGE,
)
from src.user_role.schemas import (
    AdminUserCreateSchema,
    AdminUserPasswordSchema,
    AdminUserUpdateSchema,
    PermissionPatchSchema,
    UserResponseSchema,
)

users_router = APIRouter(prefix="/users", tags=["rbac:users"])


@users_router.get("")
async def list_users(session: DbSession):
    users = await crud_list_users(session)
    return [serialize_user(user) for user in users]


@users_router.get("/{user_id}", response_model=UserResponseSchema)
async def get_user(user_id: int, session: DbSession):
    try:
        user = await crud_get_user_by_id(session, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_user(user)


@users_router.post(
    "",
    response_model=UserResponseSchema,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(RBAC_USERS_CREATE))],
)
async def create_user(payload: AdminUserCreateSchema, session: DbSession):
    try:
        user = await crud_create_user_admin(
            session,
            username=payload.username,
            password=payload.password,
            role_id=payload.role_id,
        )
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_user(user)


@users_router.patch(
    "/{user_id}",
    response_model=UserResponseSchema,
)
async def update_user(
    user_id: int,
    payload: AdminUserUpdateSchema,
    session: DbSession,
    _actor_pair=Depends(require_permission(RBAC_USERS_MANAGE)),
):
    try:
        user = await crud_update_user_admin(
            session,
            user_id=user_id,
            username=payload.username,
            role_id=payload.role_id,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_user(user)


@users_router.put(
    "/{user_id}/password",
    status_code=status.HTTP_200_OK,
)
async def set_user_password(
    user_id: int,
    payload: AdminUserPasswordSchema,
    session: DbSession,
    _actor_pair=Depends(require_permission(RBAC_USERS_MANAGE)),
):
    try:
        await crud_set_user_password_admin(session, user_id=user_id, password=payload.password)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message": "Password updated"}


@users_router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(
    user_id: int,
    session: DbSession,
    actor_pair=Depends(require_permission(RBAC_USERS_MANAGE)),
) -> Response:
    actor, _ = actor_pair
    if actor.id == user_id:
        raise HTTPException(status_code=403, detail=str(SelfDeleteForbiddenError("Self-delete is not allowed")))
    try:
        await crud_delete_user_admin(session, user_id=user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    except InvalidPermissionPatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_user(updated_user)


@users_router.post(
    "/reset",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def reset_user_permissions(session: DbSession):
    count = await crud_reset_user_permissions(session)
    return {"updated": count}
