from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.user_role.defaults import SUPERADMIN_ROLE_ID, SUPERADMIN_ROLE_NAME
from src.user_role.exceptions import (
    DuplicatePermissionKeysError,
    RoleNotFoundError,
    SuperAdminRoleImmutableError,
    UserNotFoundError,
)
from src.user_role.models import Role
from src.user_role.models import User

PermissionPatch = dict[str, bool]


@dataclass(slots=True)
class RoleRegistryResult:
    status: str
    role: str
    permissions: PermissionPatch


def is_superadmin_role(role: Role) -> bool:
    return role.id == SUPERADMIN_ROLE_ID or role.name == SUPERADMIN_ROLE_NAME


def _merge_permission_patch(
    current_permissions: PermissionPatch | None,
    permission_patch: PermissionPatch,
) -> PermissionPatch:
    merged_permissions = dict(current_permissions or {})
    merged_permissions.update(dict(permission_patch))
    return merged_permissions


# Roles CRUD
async def list_roles(session: AsyncSession) -> list[Role]:
    query_result = await session.execute(select(Role))
    return list(query_result.scalars().all())


async def patch_role_permissions(
    session: AsyncSession,
    *,
    role_id: int,
    permission_patch: PermissionPatch,
) -> Role:
    db_role = await session.get(Role, role_id)
    if db_role is None:
        raise RoleNotFoundError("Role not found")

    if is_superadmin_role(db_role):
        raise SuperAdminRoleImmutableError("SuperAdmin role permissions are immutable")

    db_role.permissions = _merge_permission_patch(db_role.permissions, permission_patch)
    session.add(db_role)
    await session.commit()
    await session.refresh(db_role)
    return db_role


async def reset_role_permissions(session: AsyncSession) -> int:
    db_roles = await list_roles(session)
    updated_count = 0

    for db_role in db_roles:
        if is_superadmin_role(db_role):
            continue
        db_role.permissions = {}
        session.add(db_role)
        updated_count += 1

    await session.commit()
    return updated_count


# Users CRUD
async def list_users(session: AsyncSession) -> list[User]:
    query_result = await session.execute(select(User))
    return list(query_result.scalars().all())


async def patch_user_permissions(
    session: AsyncSession,
    *,
    user_id: int,
    permission_patch: PermissionPatch,
) -> User:
    db_user = await session.get(User, user_id)
    if db_user is None:
        raise UserNotFoundError("User not found")

    db_user.permissions = _merge_permission_patch(db_user.permissions, permission_patch)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def reset_user_permissions(session: AsyncSession) -> int:
    db_users = await list_users(session)
    for db_user in db_users:
        db_user.permissions = {}
        session.add(db_user)

    await session.commit()
    return len(db_users)


# Role registry CRUD
async def create_or_append_role_permissions_no_overwrite(
    session: AsyncSession,
    *,
    role_name: str,
    permission_patch: PermissionPatch,
) -> RoleRegistryResult:
    existing_role = await session.scalar(select(Role).where(Role.name == role_name))
    incoming_permissions = dict(permission_patch)

    if existing_role is not None:
        current_permissions = dict(existing_role.permissions or {})
        duplicate_keys = sorted(
            key for key in incoming_permissions.keys() if key in current_permissions
        )
        if duplicate_keys:
            raise DuplicatePermissionKeysError(duplicate_keys)

        current_permissions.update(incoming_permissions)
        existing_role.permissions = current_permissions
        session.add(existing_role)
        await session.commit()
        return RoleRegistryResult(
            status="updated",
            role=existing_role.name,
            permissions=dict(existing_role.permissions or {}),
        )

    new_role = Role(
        name=role_name,
        permissions=incoming_permissions,
        title_key="",
    )
    session.add(new_role)
    await session.commit()
    return RoleRegistryResult(
        status="created",
        role=new_role.name,
        permissions=dict(new_role.permissions or {}),
    )
