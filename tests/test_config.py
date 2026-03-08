from __future__ import annotations

import pytest

from src.config import build_app_config


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")


def test_build_app_config_rejects_port_out_of_range(monkeypatch: pytest.MonkeyPatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("PORT", "70000")

    with pytest.raises(RuntimeError, match="PORT must be <= 65535"):
        build_app_config()


def test_build_app_config_rejects_non_positive_rate_limits(monkeypatch: pytest.MonkeyPatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "0")

    with pytest.raises(RuntimeError, match="RATE_LIMIT_WINDOW_SECONDS must be >= 1"):
        build_app_config()


def test_build_app_config_rejects_invalid_cors_origin(monkeypatch: pytest.MonkeyPatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver/api")

    with pytest.raises(RuntimeError, match="CORS_ALLOW_ORIGINS must not include a path"):
        build_app_config()
