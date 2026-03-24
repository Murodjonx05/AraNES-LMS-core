import types
import sys
from unittest.mock import AsyncMock, Mock

import pytest

import src.utils.super_user as super_user


class _AsyncContextManager:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Field:
    def __eq__(self, other):
        return self


class _FakeSelect:
    def where(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class _FakeSession:
    def __init__(self, existing_values=()):
        self._existing_values = iter(existing_values)
        self.execute = AsyncMock(side_effect=self._execute)
        self.scalar = AsyncMock(side_effect=self._scalar)

    async def _execute(self, stmt):
        return _FakeResult(next(self._existing_values))

    async def _scalar(self, stmt):
        return next(self._existing_values)


def _install_fake_user_model(monkeypatch):
    fake_module = types.ModuleType("src.user_role.models")

    class FakeUser:
        username = _Field()
        role_id = _Field()

        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    fake_module.User = FakeUser
    monkeypatch.setitem(sys.modules, "src.user_role.models", fake_module)
    return FakeUser


@pytest.fixture
def fake_user_model(monkeypatch):
    return _install_fake_user_model(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exists", "should_prompt"),
    [(False, True), (True, False)],
)
async def test_ensure_super_user_once(monkeypatch, exists, should_prompt):
    monkeypatch.setattr(super_user, "is_super_user_exist", AsyncMock(return_value=exists))
    create_prompt = AsyncMock()
    monkeypatch.setattr(super_user, "create_super_user_prompt", create_prompt)

    await super_user.ensure_super_user_once()

    if should_prompt:
        create_prompt.assert_awaited_once()
    else:
        create_prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_for_password_retries_until_match(monkeypatch):
    values = iter(["", "secret123", "wrong", "secret123", "secret123"])
    monkeypatch.setattr(super_user.getpass, "getpass", lambda _: next(values))

    password = await super_user.prompt_for_password()

    assert password == "secret123"


@pytest.mark.asyncio
async def test_prompt_for_username_retries_on_empty_and_duplicate(monkeypatch, fake_user_model):
    monkeypatch.setattr(super_user, "select", lambda *args, **kwargs: _FakeSelect())
    fake_session = _FakeSession([fake_user_model(username="taken"), None])
    monkeypatch.setattr(super_user, "session_scope", lambda: _AsyncContextManager(fake_session))
    usernames = iter(["", "taken", "new_user"])
    monkeypatch.setattr("builtins.input", lambda _: next(usernames))

    username = await super_user.prompt_for_username()

    assert username == "new_user"
    assert fake_session.execute.await_count == 2


@pytest.mark.asyncio
async def test_create_super_user_prompt_declines(monkeypatch, fake_user_model):
    _ = fake_user_model

    fake_auth_service_module = types.ModuleType("src.auth.service")
    fake_auth_service_module.hash_password = lambda value: f"hashed:{value}"
    monkeypatch.setitem(sys.modules, "src.auth.service", fake_auth_service_module)

    monkeypatch.setattr("builtins.input", lambda _: "n")
    monkeypatch.setattr(super_user, "session_scope", Mock())

    await super_user.create_super_user_prompt()

    super_user.session_scope.assert_not_called()


@pytest.mark.asyncio
async def test_create_super_user_requires_superadmin_role(monkeypatch, fake_user_model):
    _ = fake_user_model
    monkeypatch.setattr(super_user, "select", lambda *args, **kwargs: _FakeSelect())

    fake_auth_service_module = types.ModuleType("src.auth.service")
    fake_auth_service_module.hash_password = lambda value: f"hashed:{value}"
    monkeypatch.setitem(sys.modules, "src.auth.service", fake_auth_service_module)

    fake_role_module = types.ModuleType("src.user_role.models")

    class FakeRole:
        id = _Field()

    fake_role_module.User = fake_user_model
    fake_role_module.Role = FakeRole
    monkeypatch.setitem(sys.modules, "src.user_role.models", fake_role_module)

    fake_session = _FakeSession([None])
    monkeypatch.setattr(super_user, "session_scope", lambda *args, **kwargs: _AsyncContextManager(fake_session))

    with pytest.raises(RuntimeError, match="SuperAdmin role does not exist"):
        await super_user.create_super_user(username="admin", password="secret123")


@pytest.mark.asyncio
async def test_create_super_user_uses_auth_schema_validation(monkeypatch, fake_user_model):
    _ = fake_user_model

    fake_auth_service_module = types.ModuleType("src.auth.service")
    fake_auth_service_module.hash_password = lambda value: f"hashed:{value}"
    monkeypatch.setitem(sys.modules, "src.auth.service", fake_auth_service_module)

    with pytest.raises(ValueError, match="username: String should have at least 5 characters"):
        await super_user.create_super_user(username="adm", password="secret123")


@pytest.mark.asyncio
async def test_ensure_super_user_from_env_logs_missing_required_variables(
    monkeypatch,
):
    monkeypatch.setenv(super_user.ENV_BOOTSTRAP_ENABLE, "true")
    monkeypatch.delenv(super_user.ENV_BOOTSTRAP_USERNAME, raising=False)
    monkeypatch.delenv(super_user.ENV_BOOTSTRAP_PASSWORD, raising=False)
    log_warning = Mock()
    monkeypatch.setattr(super_user, "_log_warning", log_warning)

    created = await super_user.ensure_super_user_from_env_if_enabled()

    assert created is False
    log_warning.assert_called_once()
    wargs = log_warning.call_args.args
    rendered = wargs[0] % wargs[1:] if len(wargs) > 1 else wargs[0]
    assert super_user.ENV_BOOTSTRAP_USERNAME in rendered
    assert super_user.ENV_BOOTSTRAP_PASSWORD in rendered
