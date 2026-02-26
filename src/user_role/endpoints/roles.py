from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.database import DbSession
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


@roles_router.get("")
async def list_roles(session: DbSession):
    """
    Return a list of all roles as dictionaries.
    """
    roles = await crud_list_roles(session)
    return [serialize_role(role) for role in roles]


@roles_router.get("/{role_id}", response_model=RoleResponseSchema)
async def get_role(role_id: int, session: DbSession):
    try:
        role = await crud_get_role_by_id(session, role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_role(role)


@roles_router.post(
    "",
    response_model=RoleResponseSchema,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(RBAC_ROLES_CREATE))],
)
async def create_role(payload: RoleCreateSchema, session: DbSession):
    try:
        role = await crud_create_role(session, name=payload.name, title_key=payload.title_key)
    except RoleAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_role(role)


@roles_router.patch(
    "/{role_id}",
    response_model=RoleResponseSchema,
    dependencies=[Depends(require_permission(RBAC_ROLES_UPDATE))],
)
async def update_role(role_id: int, payload: RoleUpdateSchema, session: DbSession):
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
    return serialize_role(role)


@roles_router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(RBAC_ROLES_DELETE))],
)
async def delete_role(role_id: int, session: DbSession) -> Response:
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    except InvalidPermissionPatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
