from types import SimpleNamespace
from unittest.mock import patch

from src.runtime import build_runtime


class _DummySecurity:
    def __init__(self, config):
        self.config = config


def _make_config(database_url: str):
    return SimpleNamespace(AUTH_CONFIG=object(), DATABASE_URL=database_url)


def test_build_runtime_does_not_force_static_pool_for_file_sqlite():
    config = _make_config("sqlite+aiosqlite:///./data/test.sqlite3")

    with (
        patch("src.runtime.AuthX", _DummySecurity),
        patch("src.auth.service.configure_token_blocklist") as blocklist_mock,
        patch("src.runtime.create_async_engine") as engine_mock,
    ):
        engine_mock.return_value = object()
        build_runtime(config=config, in_memory=False)

    _, kwargs = engine_mock.call_args
    assert kwargs["echo"] is False
    assert "poolclass" not in kwargs
    assert "connect_args" not in kwargs
    blocklist_mock.assert_called_once()


def test_build_runtime_uses_static_pool_for_in_memory_mode():
    config = _make_config("sqlite+aiosqlite:///:memory:")

    with (
        patch("src.runtime.AuthX", _DummySecurity),
        patch("src.auth.service.configure_token_blocklist") as blocklist_mock,
        patch("src.runtime.create_async_engine") as engine_mock,
    ):
        engine_mock.return_value = object()
        build_runtime(config=config, in_memory=True)

    _, kwargs = engine_mock.call_args
    assert kwargs["echo"] is False
    assert "poolclass" in kwargs
    assert kwargs["connect_args"] == {"check_same_thread": False}
    blocklist_mock.assert_called_once()


def test_build_engine_kwargs_for_file_sqlite_are_minimal():
    from src.runtime import _build_engine_kwargs

    kwargs = _build_engine_kwargs("sqlite+aiosqlite:///./data/test.sqlite3", in_memory=False)
    assert kwargs == {"echo": False}


def test_build_engine_kwargs_for_in_memory_sqlite_include_threading_overrides():
    from src.runtime import _build_engine_kwargs

    kwargs = _build_engine_kwargs("sqlite+aiosqlite:///:memory:", in_memory=True)
    assert kwargs["echo"] is False
    assert "poolclass" in kwargs
    assert kwargs["connect_args"] == {"check_same_thread": False}
