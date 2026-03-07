from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from src.user_role import crud
from src.user_role.exceptions import (
    DuplicatePermissionKeysError,
    InvalidPermissionPatchError,
    RoleAlreadyExistsError,
    RoleInUseError,
    RoleNotFoundError,
    SuperAdminRoleImmutableError,
    UserNotFoundError,
)
from src.user_role.permission import (
    RBAC_CAN_MANAGE_PERMISSIONS,
    RBAC_ROLES_CREATE,
    RBAC_ROLES_DELETE,
    RBAC_ROLES_UPDATE,
    RBAC_USERS_CREATE,
    RBAC_USERS_MANAGE,
    get_registered_permission_keys,
)
from src.i18n.permission import I18N_CAN_CREATE_SMALL


@pytest.mark.asyncio
async def test_patch_role_permissions_raises_not_found():
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(RoleNotFoundError):
        await crud.patch_role_permissions(
            session, role_id=999, permission_patch={RBAC_CAN_MANAGE_PERMISSIONS: True}
        )


@pytest.mark.asyncio
async def test_patch_role_permissions_rejects_superadmin():
    role = SimpleNamespace(id=1, name="SuperAdmin", permissions={})
    session = SimpleNamespace(get=AsyncMock(return_value=role))
    with pytest.raises(SuperAdminRoleImmutableError):
        await crud.patch_role_permissions(
            session, role_id=1, permission_patch={RBAC_CAN_MANAGE_PERMISSIONS: True}
        )


@pytest.mark.asyncio
async def test_patch_user_permissions_raises_not_found():
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(UserNotFoundError):
        await crud.patch_user_permissions(
            session, user_id=999, permission_patch={RBAC_CAN_MANAGE_PERMISSIONS: True}
        )


@pytest.mark.asyncio
async def test_patch_role_permissions_rejects_unknown_keys_before_db_write():
    session = SimpleNamespace(get=AsyncMock())
    with pytest.raises(InvalidPermissionPatchError) as exc:
        await crud.patch_role_permissions(session, role_id=1, permission_patch={"x": True})

    assert exc.value.unknown_keys == ["x"]
    session.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_user_permissions_rejects_non_boolean_values():
    session = SimpleNamespace(get=AsyncMock())
    with pytest.raises(InvalidPermissionPatchError) as exc:
        await crud.patch_user_permissions(
            session, user_id=1, permission_patch={RBAC_CAN_MANAGE_PERMISSIONS: "yes"}
        )

    assert exc.value.non_boolean_keys == [RBAC_CAN_MANAGE_PERMISSIONS]
    session.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_registry_duplicate_keys_rejected():
    role = SimpleNamespace(name="Guest", permissions={RBAC_CAN_MANAGE_PERMISSIONS: True})
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=role),
        add=Mock(),
        commit=AsyncMock(),
    )

    with pytest.raises(DuplicatePermissionKeysError) as exc:
        await crud.create_or_append_role_permissions_no_overwrite(
            session,
            role_name="Guest",
            permission_patch={
                RBAC_CAN_MANAGE_PERMISSIONS: False,
                I18N_CAN_CREATE_SMALL: True,
            },
        )

    assert exc.value.duplicate_keys == [RBAC_CAN_MANAGE_PERMISSIONS]
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_registry_does_not_create_missing_role():
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        commit=AsyncMock(),
    )

    with pytest.raises(RoleNotFoundError):
        await crud.create_or_append_role_permissions_no_overwrite(
            session,
            role_name="ContentEditor1",
            permission_patch={I18N_CAN_CREATE_SMALL: True},
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_role_rejects_duplicate_name():
    session = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(
            side_effect=IntegrityError(
                statement="INSERT INTO roles ...",
                params={},
                orig=Exception("UNIQUE constraint failed: roles.name"),
            )
        ),
        rollback=AsyncMock(),
    )
    with pytest.raises(RoleAlreadyExistsError):
        await crud.create_role(session, name="Admin", title_key="role.admin.title")

    session.add.assert_called_once()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_role_rejects_role_in_use():
    role = SimpleNamespace(id=7, name="Custom")
    session = SimpleNamespace(
        get=AsyncMock(return_value=role),
        scalar=AsyncMock(return_value=2),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    with pytest.raises(RoleInUseError) as exc:
        await crud.delete_role(session, role_id=7)

    assert exc.value.user_count == 2
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_registered_permission_keys_include_new_rbac_crud_keys():
    keys = get_registered_permission_keys()
    assert RBAC_ROLES_CREATE in keys
    assert RBAC_ROLES_UPDATE in keys
    assert RBAC_ROLES_DELETE in keys
    assert RBAC_USERS_CREATE in keys
    assert RBAC_USERS_MANAGE in keys
