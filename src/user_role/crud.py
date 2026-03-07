from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from src.auth.exceptions import UsernameAlreadyExistsError
from src.auth.service import hash_password
from src.user_role.defaults import SUPERADMIN_ROLE_ID, SUPERADMIN_ROLE_NAME
from src.user_role.exceptions import (
    DuplicatePermissionKeysError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    SuperAdminRoleImmutableError,
    UserNotFoundError,
)
from src.user_role.models import Role, User
from src.user_role.permission import validate_permission_patch

PermissionPatch = dict[str, bool]


@dataclass(slots=True)
class RoleRegistryResult:
    status: str
    role_id: int
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


def _validated_permission_patch(permission_patch: dict[str, object]) -> PermissionPatch:
    return validate_permission_patch(permission_patch)


async def _get_role_by_name(session: AsyncSession, role_name: str) -> Role | None:
    return await session.scalar(select(Role).where(Role.name == role_name))


# Roles CRUD
async def list_roles(session: AsyncSession) -> list[Role]:
    result = await session.execute(
        select(Role).options(
            load_only(Role.id, Role.name, Role.title_key, Role.permissions)
        )
    )
    return list(result.scalars().all())


async def get_role_by_id(session: AsyncSession, role_id: int) -> Role:
    db_role = await session.get(Role, role_id)
    if db_role is None:
        raise RoleNotFoundError("Role not found")
    return db_role


async def create_role(
    session: AsyncSession,
    *,
    name: str,
    title_key: str,
) -> Role:
    db_role = Role(name=name, title_key=title_key, permissions={})
    session.add(db_role)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "unique constraint failed" in message and "roles.name" in message:
            raise RoleAlreadyExistsError("Role with this name already exists") from exc
        raise
    return db_role


async def update_role(
    session: AsyncSession,
    *,
    role_id: int,
    name: str | None = None,
    title_key: str | None = None,
) -> Role:
    db_role = await get_role_by_id(session, role_id)
    if is_superadmin_role(db_role):
        raise SuperAdminRoleImmutableError("SuperAdmin role is immutable")

    if name is not None and name != db_role.name:
        db_role.name = name
    if title_key is not None:
        db_role.title_key = title_key

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "unique constraint failed" in message and "roles.name" in message:
            raise RoleAlreadyExistsError("Role with this name already exists") from exc
        raise
    return db_role


async def delete_role(session: AsyncSession, *, role_id: int) -> None:
    db_role = await get_role_by_id(session, role_id)
    if is_superadmin_role(db_role):
        raise SuperAdminRoleImmutableError("SuperAdmin role is immutable")

    user_count = int(
        (await session.scalar(select(func.count()).select_from(User).where(User.role_id == role_id))) or 0
    )
    if user_count > 0:
        raise RoleInUseError(user_count)

    await session.delete(db_role)
    await session.commit()


async def patch_role_permissions(
    session: AsyncSession,
    *,
    role_id: int,
    permission_patch: PermissionPatch,
) -> Role:
    permission_patch = _validated_permission_patch(permission_patch)

    db_role = await session.get(Role, role_id)
    if db_role is None:
        raise RoleNotFoundError("Role not found")

    if is_superadmin_role(db_role):
        raise SuperAdminRoleImmutableError("SuperAdmin role permissions are immutable")

    db_role.permissions = _merge_permission_patch(db_role.permissions, permission_patch)
    await session.commit()
    return db_role


async def reset_role_permissions(session: AsyncSession) -> int:
    filter_clause = (Role.id != SUPERADMIN_ROLE_ID) & (Role.name != SUPERADMIN_ROLE_NAME)
    updated_count = int(
        (await session.scalar(select(func.count()).select_from(Role).where(filter_clause))) or 0
    )
    if updated_count == 0:
        return 0
    await session.execute(update(Role).where(filter_clause).values(permissions={}))
    await session.commit()
    return updated_count


# Users CRUD
async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(load_only(User.id, User.username, User.role_id, User.permissions))
    )
    return list(result.scalars().all())


async def get_user_by_id(session: AsyncSession, user_id: int) -> User:
    db_user = await session.get(User, user_id)
    if db_user is None:
        raise UserNotFoundError("User not found")
    return db_user


async def create_user_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role_id: int,
) -> User:
    role_exists = await session.scalar(select(Role.id).where(Role.id == role_id).limit(1))
    if role_exists is None:
        raise RoleNotFoundError("Role not found")

    # Avoid an extra pre-check query; rely on DB uniqueness for username conflicts.

    db_user = User(
        username=username,
        password=hash_password(password),
        role_id=role_id,
        permissions={},
    )
    session.add(db_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "unique constraint failed" in message and "users.username" in message:
            raise UsernameAlreadyExistsError("Username already exists") from exc
        raise
    return db_user


async def update_user_admin(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None = None,
    role_id: int | None = None,
) -> User:
    db_user = await get_user_by_id(session, user_id)

    if username is not None and username != db_user.username:
        db_user.username = username

    if role_id is not None:
        if await session.get(Role, role_id) is None:
            raise RoleNotFoundError("Role not found")
        db_user.role_id = role_id

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "unique constraint failed" in message and "users.username" in message:
            raise UsernameAlreadyExistsError("Username already exists") from exc
        raise
    return db_user


async def set_user_password_admin(
    session: AsyncSession,
    *,
    user_id: int,
    password: str,
) -> User:
    db_user = await get_user_by_id(session, user_id)
    db_user.password = hash_password(password)
    await session.commit()
    return db_user


async def delete_user_admin(session: AsyncSession, *, user_id: int) -> None:
    db_user = await get_user_by_id(session, user_id)
    await session.delete(db_user)
    await session.commit()


async def patch_user_permissions(
    session: AsyncSession,
    *,
    user_id: int,
    permission_patch: PermissionPatch,
) -> User:
    permission_patch = _validated_permission_patch(permission_patch)

    db_user = await session.get(User, user_id)
    if db_user is None:
        raise UserNotFoundError("User not found")

    db_user.permissions = _merge_permission_patch(db_user.permissions, permission_patch)
    await session.commit()
    return db_user


async def reset_user_permissions(session: AsyncSession) -> int:
    updated_count = int((await session.scalar(select(func.count()).select_from(User))) or 0)
    if updated_count == 0:
        return 0
    await session.execute(update(User).values(permissions={}))
    await session.commit()
    return updated_count


# Role registry CRUD
async def create_or_append_role_permissions_no_overwrite(
    session: AsyncSession,
    *,
    role_name: str,
    permission_patch: PermissionPatch,
) -> RoleRegistryResult:
    permission_patch = _validated_permission_patch(permission_patch)

    existing_role = await _get_role_by_name(session, role_name)
    incoming_permissions = dict(permission_patch)

    if existing_role is None:
        raise RoleNotFoundError("Role not found")

    current_permissions = dict(existing_role.permissions or {})
    duplicate_keys = sorted(
        key for key in incoming_permissions.keys() if key in current_permissions
    )
    if duplicate_keys:
        raise DuplicatePermissionKeysError(duplicate_keys)

    current_permissions.update(incoming_permissions)
    existing_role.permissions = current_permissions
    await session.commit()
    return RoleRegistryResult(
        status="updated",
        role_id=existing_role.id,
        role=existing_role.name,
        permissions=dict(existing_role.permissions or {}),
    )
