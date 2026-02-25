from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.user_role import crud
from src.user_role.exceptions import (
    DuplicatePermissionKeysError,
    RoleNotFoundError,
    SuperAdminRoleImmutableError,
    UserNotFoundError,
)


@pytest.mark.asyncio
async def test_patch_role_permissions_raises_not_found():
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(RoleNotFoundError):
        await crud.patch_role_permissions(session, role_id=999, permission_patch={"x": True})


@pytest.mark.asyncio
async def test_patch_role_permissions_rejects_superadmin():
    role = SimpleNamespace(id=1, name="SuperAdmin", permissions={})
    session = SimpleNamespace(get=AsyncMock(return_value=role))
    with pytest.raises(SuperAdminRoleImmutableError):
        await crud.patch_role_permissions(session, role_id=1, permission_patch={"x": True})


@pytest.mark.asyncio
async def test_patch_user_permissions_raises_not_found():
    session = SimpleNamespace(get=AsyncMock(return_value=None))
    with pytest.raises(UserNotFoundError):
        await crud.patch_user_permissions(session, user_id=999, permission_patch={"x": True})


@pytest.mark.asyncio
async def test_role_registry_duplicate_keys_rejected():
    role = SimpleNamespace(name="Guest", permissions={"existing": True})
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=role),
        add=Mock(),
        commit=AsyncMock(),
    )

    with pytest.raises(DuplicatePermissionKeysError) as exc:
        await crud.create_or_append_role_permissions_no_overwrite(
            session,
            role_name="Guest",
            permission_patch={"existing": False, "new": True},
        )

    assert exc.value.duplicate_keys == ["existing"]
    session.commit.assert_not_awaited()
