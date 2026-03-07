from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.database import DbSession
from src.user_role.cache import RbacCacheService, get_request_rbac_cache_service
from src.user_role.crud import (
    create_role as crud_create_role,
    delete_role as crud_delete_role,
    get_role_by_id as crud_get_role_by_id,
    list_roles as crud_list_roles,
    patch_role_permissions as crud_patch_role_permissions,
    reset_role_permissions as crud_reset_role_permissions,
    update_role as crud_update_role,
)
from src.user_role.endpoints.serializers import serialize_role
from src.user_role.exceptions import (
    InvalidPermissionPatchError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    SuperAdminRoleImmutableError,
)
from src.user_role.middlewares import require_permission
from src.user_role.permission import (
    RBAC_CAN_MANAGE_PERMISSIONS,
    RBAC_ROLES_READ,
    RBAC_ROLES_CREATE,
    RBAC_ROLES_DELETE,
    RBAC_ROLES_UPDATE,
)
from src.user_role.schemas import (
    PermissionPatchSchema,
    RoleCreateSchema,
    RoleResponseSchema,
    RoleUpdateSchema,
)

roles_router = APIRouter(prefix="/roles", tags=["rbac:roles"])


@roles_router.get(
    "",
    dependencies=[Depends(require_permission(RBAC_ROLES_READ))],
)
async def list_roles(
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    cached_roles = await cache_service.get_role_list()
    if cached_roles is not None:
        return cached_roles
    serialized_roles = [serialize_role(role) for role in await crud_list_roles(session)]
    await cache_service.set_role_list(serialized_roles)
    return serialized_roles


@roles_router.get(
    "/{role_id}",
    response_model=RoleResponseSchema,
    dependencies=[Depends(require_permission(RBAC_ROLES_READ))],
)
async def get_role(
    role_id: int,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    cached_role = await cache_service.get_role(role_id)
    if cached_role is not None:
        return cached_role
    try:
        role = await crud_get_role_by_id(session, role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    serialized_role = serialize_role(role)
    await cache_service.set_role(role_id, serialized_role)
    return serialized_role


@roles_router.post(
    "",
    response_model=RoleResponseSchema,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(RBAC_ROLES_CREATE))],
)
async def create_role(
    payload: RoleCreateSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    try:
        role = await crud_create_role(session, name=payload.name, title_key=payload.title_key)
    except RoleAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    serialized_role = serialize_role(role)
    await cache_service.invalidate_role_list()
    await cache_service.set_role(role.id, serialized_role)
    return serialized_role


@roles_router.patch(
    "/{role_id}",
    response_model=RoleResponseSchema,
    dependencies=[Depends(require_permission(RBAC_ROLES_UPDATE))],
)
async def update_role(
    role_id: int,
    payload: RoleUpdateSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    try:
        role = await crud_update_role(
            session,
            role_id=role_id,
            name=payload.name,
            title_key=payload.title_key,
        )
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SuperAdminRoleImmutableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RoleAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    serialized_role = serialize_role(role)
    await cache_service.invalidate_role_list()
    await cache_service.set_role(role_id, serialized_role)
    return serialized_role


@roles_router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(RBAC_ROLES_DELETE))],
)
async def delete_role(
    role_id: int,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
) -> Response:
    try:
        await crud_delete_role(session, role_id=role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SuperAdminRoleImmutableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RoleInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "user_count": exc.user_count},
        ) from exc
    await cache_service.invalidate_role(role_id)
    await cache_service.invalidate_role_list()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@roles_router.patch(
    "/{role_id}/permissions",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def patch_role_permissions(
    role_id: int,
    permissions: PermissionPatchSchema,
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
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
    except InvalidPermissionPatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    serialized_role = serialize_role(updated_role)
    await cache_service.invalidate_role_list()
    await cache_service.set_role(role_id, serialized_role)
    return serialized_role


@roles_router.post(
    "/reset",
    dependencies=[Depends(require_permission(RBAC_CAN_MANAGE_PERMISSIONS))],
)
async def reset_role_permissions(
    session: DbSession,
    cache_service: RbacCacheService = Depends(get_request_rbac_cache_service),
):
    """
    Reset permissions for all roles except the SuperAdmin role.
    Returns the count of updated roles.
    """
    roles = await crud_list_roles(session)
    updated_count = await crud_reset_role_permissions(session)
    for role in roles:
        await cache_service.invalidate_role(role.id)
    await cache_service.invalidate_role_list()
    return {"updated": updated_count}
