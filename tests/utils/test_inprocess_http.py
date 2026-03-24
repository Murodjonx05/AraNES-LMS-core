from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.utils.inprocess_http import (
    AppHttpRouteResolver,
    InternalAwareHttpClient,
    attach_inprocess_http,
    close_inprocess_http,
)


class _CallRecorder:
    def __init__(self, label: str):
        self.label = label
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> str:
        self.calls.append((method, url, kwargs))
        return self.label


class _FakeAsyncClient:
    def __init__(self, recorder: _CallRecorder):
        self._recorder = recorder

    async def request(self, method: str, url: str, **kwargs: Any) -> str:
        return await self._recorder.request(method, url, **kwargs)

    async def aclose(self) -> None:
        return None


class _ResolverRecorder:
    def __init__(self):
        self.calls: list[tuple[str, str | httpx.URL, dict[str, Any]]] = []

    async def request(self, method: str, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        req = httpx.Request(method, str(url))
        return httpx.Response(200, request=req, json={"ok": True})


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/auth/me")
    async def _auth_me():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def _auth_login():
        return {"access_token": "x"}

    @app.get("/api/v1/rbac/users/{user_id}")
    async def _rbac_user(user_id: int):
        return {"user_id": user_id}

    return app


def _make_request(app: FastAPI, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/test",
        "raw_path": b"/api/test",
        "query_string": b"",
        "headers": headers or [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "app": app,
        "root_path": "",
    }
    return Request(scope)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "url", "expected_target"),
    [
        ("GET", "/api/v1/auth/me", "local"),
        ("POST", "/api/v1/auth/login", "local"),
        ("GET", "https://example.com/docs", "external"),
        ("GET", "https://example.com/openapi.json", "external"),
    ],
)
async def test_resolver_routes_local_and_external_targets(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    url: str,
    expected_target: str,
):
    app = _build_app()
    resolver = attach_inprocess_http(app)
    local = _CallRecorder("local")
    external = _CallRecorder("external")
    monkeypatch.setattr(resolver, "_local_client", _FakeAsyncClient(local))
    monkeypatch.setattr(resolver, "_external_client", _FakeAsyncClient(external))

    try:
        result = await resolver.request(method, url)
        assert result == expected_target
        if expected_target == "local":
            assert len(local.calls) == 1
            assert len(external.calls) == 0
        else:
            assert len(local.calls) == 0
            assert len(external.calls) == 1
    finally:
        await close_inprocess_http(app)


@pytest.mark.asyncio
async def test_resolver_matches_dynamic_api_paths(monkeypatch: pytest.MonkeyPatch):
    app = _build_app()
    resolver = attach_inprocess_http(app)
    local = _CallRecorder("local")
    external = _CallRecorder("external")
    monkeypatch.setattr(resolver, "_local_client", _FakeAsyncClient(local))
    monkeypatch.setattr(resolver, "_external_client", _FakeAsyncClient(external))

    try:
        result = await resolver.request("GET", "/api/v1/rbac/users/123")
        assert result == "local"
        assert len(local.calls) == 1
        assert local.calls[0][1] == "/api/v1/rbac/users/123"
        assert len(external.calls) == 0
    finally:
        await close_inprocess_http(app)


@pytest.mark.asyncio
async def test_resolver_uses_external_http_for_non_local_absolute_url(
    monkeypatch: pytest.MonkeyPatch,
):
    app = _build_app()
    resolver = attach_inprocess_http(app)
    local = _CallRecorder("local")
    external = _CallRecorder("external")
    monkeypatch.setattr(resolver, "_local_client", _FakeAsyncClient(local))
    monkeypatch.setattr(resolver, "_external_client", _FakeAsyncClient(external))

    try:
        result = await resolver.request("GET", "https://example.com/health")
        assert result == "external"
        assert len(local.calls) == 0
        assert len(external.calls) == 1
        assert external.calls[0][1] == "https://example.com/health"
    finally:
        await close_inprocess_http(app)


@pytest.mark.asyncio
async def test_resolver_treats_absolute_external_api_urls_as_external(
    monkeypatch: pytest.MonkeyPatch,
):
    app = _build_app()
    resolver = attach_inprocess_http(app)
    local = _CallRecorder("local")
    external = _CallRecorder("external")
    monkeypatch.setattr(resolver, "_local_client", _FakeAsyncClient(local))
    monkeypatch.setattr(resolver, "_external_client", _FakeAsyncClient(external))

    try:
        result = await resolver.request("GET", "https://example.com/api/v1/auth/me")
        assert result == "external"
        assert len(local.calls) == 0
        assert len(external.calls) == 1
        assert external.calls[0][1] == "https://example.com/api/v1/auth/me"
    finally:
        await close_inprocess_http(app)


@pytest.mark.asyncio
async def test_resolver_allows_absolute_api_urls_for_explicit_internal_host(
    monkeypatch: pytest.MonkeyPatch,
):
    app = _build_app()
    resolver = attach_inprocess_http(app)
    local = _CallRecorder("local")
    external = _CallRecorder("external")
    monkeypatch.setattr(resolver, "_local_client", _FakeAsyncClient(local))
    monkeypatch.setattr(resolver, "_external_client", _FakeAsyncClient(external))

    try:
        result = await resolver.request("GET", "http://inprocess.local/api/v1/auth/me")
        assert result == "local"
        assert len(local.calls) == 1
        assert local.calls[0][1] == "/api/v1/auth/me"
        assert len(external.calls) == 0
    finally:
        await close_inprocess_http(app)


@pytest.mark.asyncio
async def test_internal_client_forwards_authorization_and_preserves_explicit_header():
    app = _build_app()
    request = _make_request(app, headers=[(b"authorization", b"Bearer inherited-token")])
    resolver = _ResolverRecorder()
    client = InternalAwareHttpClient(request=request, resolver=resolver)  # type: ignore[arg-type]

    await client.get("/api/v1/auth/me")
    forwarded_headers = httpx.Headers(resolver.calls[0][2]["headers"])
    assert forwarded_headers["authorization"] == "Bearer inherited-token"

    await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer explicit-token"},
    )
    explicit_headers = httpx.Headers(resolver.calls[1][2]["headers"])
    assert explicit_headers["authorization"] == "Bearer explicit-token"


@pytest.mark.asyncio
async def test_resolver_route_match_cache_is_bounded():
    app = _build_app()
    resolver = AppHttpRouteResolver(app, route_cache_maxsize=8)
    for i in range(24):
        resolver._is_local_api_path("GET", f"/api/miss/{i}")
    assert len(resolver._route_match_lru) == 8
    assert ("GET", "/api/miss/0") not in resolver._route_match_lru
    assert ("GET", "/api/miss/23") in resolver._route_match_lru


@pytest.mark.asyncio
async def test_resolver_route_match_cache_keeps_recently_used_entries():
    app = _build_app()
    resolver = AppHttpRouteResolver(app, route_cache_maxsize=3)

    resolver._is_local_api_path("GET", "/api/miss/1")
    resolver._is_local_api_path("GET", "/api/miss/2")
    resolver._is_local_api_path("GET", "/api/miss/3")
    resolver._is_local_api_path("GET", "/api/miss/1")
    resolver._is_local_api_path("GET", "/api/miss/4")

    assert ("GET", "/api/miss/1") in resolver._route_match_lru
    assert ("GET", "/api/miss/2") not in resolver._route_match_lru
    assert ("GET", "/api/miss/4") in resolver._route_match_lru


def test_resolver_uses_hardened_default_external_timeout():
    app = _build_app()
    resolver = AppHttpRouteResolver(app)

    timeout = resolver._external_timeout

    assert timeout.connect == 2.0
    assert timeout.read == 5.0
    assert timeout.write == 5.0
    assert timeout.pool == 5.0


@pytest.mark.asyncio
async def test_resolver_raises_for_relative_non_local_url():
    app = _build_app()
    resolver = attach_inprocess_http(app)
    try:
        with pytest.raises(ValueError, match="relative non-local URL"):
            await resolver.request("GET", "/health")
    finally:
        await close_inprocess_http(app)
