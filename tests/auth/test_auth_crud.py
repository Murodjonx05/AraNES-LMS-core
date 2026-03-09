from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from src.auth import crud
from src.auth.exceptions import UsernameAlreadyExistsError


class _ScalarResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


@pytest.mark.asyncio
async def test_create_user_rejects_postgres_duplicate_username():
    session = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(
            side_effect=IntegrityError(
                statement="INSERT INTO users ...",
                params={},
                orig=Exception('duplicate key value violates unique constraint "users_username_key"'),
            )
        ),
        rollback=AsyncMock(),
    )

    with pytest.raises(UsernameAlreadyExistsError):
        await crud.create_user(
            session,
            username="student01",
            password_hash="hash",
            role_id=6,
            permissions={},
        )

    session.add.assert_called_once()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_or_create_default_signup_role_rejects_default_role_drift():
    config = SimpleNamespace(
        DEFAULT_SIGNUP_ROLE_ID=6,
        DEFAULT_SIGNUP_ROLE_NAME="Student",
        DEFAULT_SIGNUP_ROLE_TITLE_KEY="role.student.title",
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=_ScalarResult(
                [SimpleNamespace(id=6, name="CustomStudent", title_key="role.custom.title")]
            )
        ),
        add=Mock(),
        flush=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="Default signup role drift detected"):
        await crud.get_or_create_default_signup_role_with_config(session, config=config)  # type: ignore[arg-type]

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_or_create_default_signup_role_rejects_split_default_role_mapping():
    config = SimpleNamespace(
        DEFAULT_SIGNUP_ROLE_ID=6,
        DEFAULT_SIGNUP_ROLE_NAME="Student",
        DEFAULT_SIGNUP_ROLE_TITLE_KEY="role.student.title",
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=_ScalarResult(
                [
                    SimpleNamespace(id=6, name="CustomStudent", title_key="role.custom.title"),
                    SimpleNamespace(id=9, name="Student", title_key="role.student.title"),
                ]
            )
        ),
        add=Mock(),
        flush=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="Default signup role mapping drift detected"):
        await crud.get_or_create_default_signup_role_with_config(session, config=config)  # type: ignore[arg-type]

    session.add.assert_not_called()
    session.flush.assert_not_awaited()
