from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.auth.exceptions import UsernameAlreadyExistsError
from src.database import DbSession
from src.user_role.cache import RbacCacheService, get_request_rbac_cache_service
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
    RBAC_USERS_READ,
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

users_router = APIRouter(prefix="/users", tags=["users:+rbac"])


@users_router.get(
    "",
    dependencies=[Depends(require_permission(RBAC_USERS_READ))],
)
async def list_users(
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    cached_users = await cache_service.get_user_list()
    if cached_users is not None:
        return cached_users
    serialized_users = [serialize_user(user) for user in await crud_list_users(session)]
    await cache_service.set_user_list(serialized_users)
    return serialized_users


@users_router.get(
    "/{user_id}",
    response_model=UserResponseSchema,
    dependencies=[Depends(require_permission(RBAC_USERS_READ))],
)
async def get_user(
    user_id: int,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    cached_user = await cache_service.get_user(user_id)
    if cached_user is not None:
        return cached_user
    try:
        user = await crud_get_user_by_id(session, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    serialized_user = serialize_user(user)
    await cache_service.set_user(user_id, serialized_user)
    return serialized_user


@users_router.post(
    "",
    response_model=UserResponseSchema,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(RBAC_USERS_CREATE))],
)
async def create_user(
    payload: AdminUserCreateSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
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
    serialized_user = serialize_user(user)
    await cache_service.invalidate_user_list()
    await cache_service.set_user(user.id, serialized_user)
    return serialized_user


@users_router.patch(
    "/{user_id}",
    response_model=UserResponseSchema,
)
async def update_user(
    user_id: int,
    payload: AdminUserUpdateSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
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
    serialized_user = serialize_user(user)
    await cache_service.invalidate_user_list()
    await cache_service.set_user(user_id, serialized_user)
    return serialized_user


@users_router.put(
    "/{user_id}/password",
    status_code=status.HTTP_200_OK,
)
async def set_user_password(
    user_id: int,
    payload: AdminUserPasswordSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
    _actor_pair=Depends(require_permission(RBAC_USERS_MANAGE)),
):
    try:
        await crud_set_user_password_admin(session, user_id=user_id, password=payload.password)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await cache_service.invalidate_user(user_id)
    return {"message": "Password updated"}


@users_router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(
    user_id: int,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
    actor=Depends(require_permission(RBAC_USERS_MANAGE)),
) -> Response:
    if actor.user_id == user_id:
        raise HTTPException(status_code=403, detail=str(SelfDeleteForbiddenError("Self-delete is not allowed")))
    try:
        await crud_delete_user_admin(session, user_id=user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await cache_service.invalidate_user(user_id)
    await cache_service.invalidate_user_list()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_router.patch(
    "/{user_id}/permissions",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def patch_user_permissions(
    user_id: int,
    permissions: PermissionPatchSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
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
    serialized_user = serialize_user(updated_user)
    await cache_service.invalidate_user_list()
    await cache_service.set_user(user_id, serialized_user)
    return serialized_user


@users_router.post(
    "/reset",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def reset_user_permissions(
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    users = await crud_list_users(session)
    count = await crud_reset_user_permissions(session)
    for user in users:
        await cache_service.invalidate_user(user.id)
    await cache_service.invalidate_user_list()
    return {"updated": count}
