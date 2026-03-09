from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.user_role import bootstrap


class _ScalarResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


@pytest.mark.asyncio
async def test_seed_roles_if_missing_rejects_default_role_id_name_drift(
    monkeypatch: pytest.MonkeyPatch,
):
    drifted_role = SimpleNamespace(id=6, name="CustomStudent", title_key="role.custom.title", permissions={})
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult([drifted_role])),
        add_all=Mock(),
        dirty=False,
        commit=AsyncMock(),
    )
    init_permissions_mock = AsyncMock()
    monkeypatch.setattr(bootstrap.RBAC_SERVICE, "init_role_permissions_if_missing", init_permissions_mock)

    with pytest.raises(RuntimeError, match="Default role drift detected"):
        await bootstrap.seed_roles_if_missing(session, commit=False)

    session.add_all.assert_not_called()
    session.commit.assert_not_awaited()
    init_permissions_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_roles_if_missing_rejects_split_default_role_mapping(
    monkeypatch: pytest.MonkeyPatch,
):
    wrong_id_role = SimpleNamespace(id=6, name="CustomStudent", title_key="role.custom.title", permissions={})
    wrong_name_role = SimpleNamespace(id=99, name="Student", title_key="role.student.title", permissions={})
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult([wrong_id_role, wrong_name_role])),
        add_all=Mock(),
        dirty=False,
        commit=AsyncMock(),
    )
    init_permissions_mock = AsyncMock()
    monkeypatch.setattr(bootstrap.RBAC_SERVICE, "init_role_permissions_if_missing", init_permissions_mock)

    with pytest.raises(RuntimeError, match="Default role mapping drift detected"):
        await bootstrap.seed_roles_if_missing(session, commit=False)

    session.add_all.assert_not_called()
    session.commit.assert_not_awaited()
    init_permissions_mock.assert_not_awaited()
