from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.user_role import middlewares


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


def _build_request():
    return SimpleNamespace(state=SimpleNamespace())


@pytest.mark.asyncio
async def test_get_current_actor_reuses_cached_user_role_pair():
    user = SimpleNamespace(id=11, role_id=3, permissions={"edit": False, "delete": True})
    role = SimpleNamespace(id=3, permissions={"edit": True, "read": True})
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result((user, role))))
    request = _build_request()
    payload = {"uid": 11, "sub": "alice"}

    pair = await middlewares.get_current_user_with_role(
        request=request,  # type: ignore[arg-type]
        session=session,
        payload=payload,
    )
    actor = await middlewares.get_current_actor(
        request=request,  # type: ignore[arg-type]
        session=session,
        payload=payload,
    )

    assert pair == (user, role)
    assert actor.user_id == 11
    assert actor.role_id == 3
    assert actor.effective_permissions == {"edit": False, "read": True, "delete": True}
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_current_actor_builds_from_cached_user_role_pair_without_query():
    user = SimpleNamespace(id=5, role_id=2, permissions={"manage": True})
    role = SimpleNamespace(id=2, permissions={"manage": False, "read": True})
    session = SimpleNamespace(execute=AsyncMock())
    request = _build_request()
    request.state._current_user_with_role = (user, role)

    actor = await middlewares.get_current_actor(
        request=request,  # type: ignore[arg-type]
        session=session,
        payload={"uid": 5, "sub": "bob"},
    )

    assert actor.user_id == 5
    assert actor.role_id == 2
    assert actor.effective_permissions == {"manage": True, "read": True}
    session.execute.assert_not_awaited()
