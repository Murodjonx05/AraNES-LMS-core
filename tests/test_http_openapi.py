"""Tests for HTTP OpenAPI security metadata and error responses."""
from __future__ import annotations

import pytest
from fastapi import FastAPI

from src.app import create_app
from src.config import build_app_config
from src.runtime import build_runtime, reset_default_runtime


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-openapi")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://testserver")


@pytest.fixture
def app_with_openapi(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    _set_required_env(monkeypatch)
    reset_default_runtime()
    config = build_app_config()
    runtime = build_runtime(config)
    app = create_app(runtime)
    try:
        yield app
    finally:
        reset_default_runtime()


def test_openapi_includes_bearer_auth_scheme(app_with_openapi: FastAPI):
    schema = app_with_openapi.openapi()
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" in schemes
    assert schemes["BearerAuth"].get("type") == "http"
    assert schemes["BearerAuth"].get("scheme") == "bearer"
    assert schemes["BearerAuth"].get("bearerFormat") == "JWT"


def test_openapi_protected_route_has_security(app_with_openapi: FastAPI):
    schema = app_with_openapi.openapi()
    paths = schema.get("paths", {})
    me = paths.get("/api/v1/auth/me", {})
    assert me, "Expected /api/v1/auth/me in OpenAPI paths"
    get_op = me.get("get", {})
    assert get_op.get("security") == [{"BearerAuth": []}]


def test_openapi_open_route_has_no_security(app_with_openapi: FastAPI):
    schema = app_with_openapi.openapi()
    paths = schema.get("paths", {})
    login = paths.get("/api/v1/auth/login", {})
    assert login, "Expected /api/v1/auth/login in OpenAPI paths"
    post_op = login.get("post", {})
    assert post_op.get("security") == []
