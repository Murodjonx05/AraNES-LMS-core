from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.i18n.permission import I18N_CAN_READ_SMALL
from src.user_role import bootstrap
from src.user_role.defaults import DEFAULT_ROLES, PLUGIN_ROLE_NAME, PLUGIN_ROLE_TITLE_KEY
from src.user_role.permission import RBACService, RBAC_ROLES_READ
from src.user_role.translates import ROLE_TITLE_TRANSLATES


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


@pytest.mark.asyncio
async def test_seed_roles_if_missing_reuses_loaded_roles_for_permission_backfill():
    execute_calls = {"count": 0}

    async def _execute(statement):
        del statement
        execute_calls["count"] += 1
        if execute_calls["count"] > 1:
            raise AssertionError("roles should not be scanned twice")
        existing_roles = [
            SimpleNamespace(id=role_id, name=role_name, title_key=role_title_key, permissions={})
            for role_id, role_name, role_title_key in DEFAULT_ROLES
        ]
        return _ScalarResult(existing_roles)

    session = SimpleNamespace(
        execute=AsyncMock(side_effect=_execute),
        add_all=Mock(),
        add=Mock(),
        dirty=False,
        commit=AsyncMock(),
    )

    created = await bootstrap.seed_roles_if_missing(session, commit=False)

    assert created == 0
    assert execute_calls["count"] == 1
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_roles_if_missing_queries_only_default_role_candidates(monkeypatch: pytest.MonkeyPatch):
    statements: list[object] = []
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=lambda statement: statements.append(statement) or _ScalarResult([])
        ),
        add_all=Mock(),
        add=Mock(),
        dirty=False,
        commit=AsyncMock(),
    )
    init_permissions_mock = AsyncMock()
    monkeypatch.setattr(bootstrap.RBAC_SERVICE, "init_role_permissions_if_missing", init_permissions_mock)

    created = await bootstrap.seed_roles_if_missing(session, commit=False)

    assert created == len(DEFAULT_ROLES)
    assert len(statements) == 1
    sql = str(statements[0])
    assert "WHERE" in sql
    assert "roles.id IN" in sql
    assert "roles.name IN" in sql
    init_permissions_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_roles_if_missing_creates_plugin_as_name_based_default_role(
    monkeypatch: pytest.MonkeyPatch,
):
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult([])),
        add_all=Mock(),
        add=Mock(),
        dirty=False,
        commit=AsyncMock(),
    )
    init_permissions_mock = AsyncMock()
    monkeypatch.setattr(bootstrap.RBAC_SERVICE, "init_role_permissions_if_missing", init_permissions_mock)

    created = await bootstrap.seed_roles_if_missing(session, commit=False)

    assert created == len(DEFAULT_ROLES)
    added_roles = session.add_all.call_args.args[0]
    plugin_role = next(role for role in added_roles if role.name == PLUGIN_ROLE_NAME)
    assert plugin_role.id is None
    assert plugin_role.title_key == PLUGIN_ROLE_TITLE_KEY
    assert plugin_role.permissions[RBAC_ROLES_READ] is True
    assert plugin_role.permissions[I18N_CAN_READ_SMALL] is True


def test_role_title_translates_include_plugin():
    assert ROLE_TITLE_TRANSLATES[PLUGIN_ROLE_TITLE_KEY]["en"] == "Plugin"


@pytest.mark.asyncio
async def test_rbac_service_init_role_permissions_queries_when_roles_not_provided():
    role = SimpleNamespace(name="Admin", permissions={})
    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult([role])), add=Mock(), commit=AsyncMock())
    service = RBACService({"Admin": {"rbac_roles_read": True}})

    updated = await service.init_role_permissions_if_missing(session, commit=False)

    assert updated == 1
    session.execute.assert_awaited_once()
