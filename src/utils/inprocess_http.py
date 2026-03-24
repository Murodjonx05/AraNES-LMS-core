from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute

_LOCAL_CLIENT_BASE_URL = "http://inprocess.local"
_RESOLVER_STATE_KEY = "inprocess_http_resolver"
_INTERNAL_HOST_ALLOWLIST = frozenset({"inprocess.local"})

_DEFAULT_ROUTE_CACHE_MAX_ENTRIES = 4096
_DEFAULT_EXTERNAL_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_DEFAULT_LOCAL_TIMEOUT = httpx.Timeout(120.0, connect=2.0, pool=5.0)


def _resolver_options_from_app(app: FastAPI) -> tuple[int, httpx.Timeout, httpx.Timeout]:
    runtime = getattr(app.state, "runtime", None)
    cfg = getattr(runtime, "config", None)
    if cfg is None:
        return _DEFAULT_ROUTE_CACHE_MAX_ENTRIES, _DEFAULT_EXTERNAL_TIMEOUT, _DEFAULT_LOCAL_TIMEOUT
    return (
        int(cfg.INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES),
        httpx.Timeout(
            cfg.INPROCESS_HTTP_EXTERNAL_TIMEOUT_SECONDS,
            connect=cfg.INPROCESS_HTTP_EXTERNAL_CONNECT_TIMEOUT_SECONDS,
        ),
        httpx.Timeout(
            cfg.INPROCESS_HTTP_LOCAL_READ_TIMEOUT_SECONDS,
            connect=2.0,
            pool=5.0,
        ),
    )


class AppHttpRouteResolver:
    def __init__(
        self,
        app: FastAPI,
        *,
        route_cache_maxsize: int = _DEFAULT_ROUTE_CACHE_MAX_ENTRIES,
        external_timeout: httpx.Timeout | None = None,
        local_timeout: httpx.Timeout | None = None,
    ) -> None:
        self._app = app
        self._static_api_routes: set[tuple[str, str]] = set()
        self._dynamic_api_routes: list[tuple[set[str], re.Pattern[str]]] = []
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
                continue
            methods = {method.upper() for method in (route.methods or set())}
            if "{" in route.path:
                self._dynamic_api_routes.append((methods, route.path_regex))
            else:
                for method in methods:
                    self._static_api_routes.add((method, route.path))
        self._route_cache_maxsize = max(1, route_cache_maxsize)
        self._route_match_lru: OrderedDict[tuple[str, str], bool] = OrderedDict()
        self._external_timeout = external_timeout or _DEFAULT_EXTERNAL_TIMEOUT
        self._local_timeout = local_timeout or _DEFAULT_LOCAL_TIMEOUT
        self._local_client: httpx.AsyncClient | None = None
        self._external_client: httpx.AsyncClient | None = None

    def _get_local_client(self) -> httpx.AsyncClient:
        client = self._local_client
        if client is None:
            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self._app),
                base_url=_LOCAL_CLIENT_BASE_URL,
                timeout=self._local_timeout,
            )
            self._local_client = client
        return client

    def _get_external_client(self) -> httpx.AsyncClient:
        client = self._external_client
        if client is None:
            client = httpx.AsyncClient(timeout=self._external_timeout)
            self._external_client = client
        return client

    def _is_local_api_path(self, method: str, path: str) -> bool:
        key = (method.upper(), path)
        if key in self._route_match_lru:
            self._route_match_lru.move_to_end(key)
            return self._route_match_lru[key]

        if not path.startswith("/api"):
            result = False
        elif key in self._static_api_routes:
            result = True
        else:
            result = False
            for methods, path_regex in self._dynamic_api_routes:
                if key[0] not in methods:
                    continue
                if path_regex.match(path):
                    result = True
                    break

        self._route_match_lru[key] = result
        self._route_match_lru.move_to_end(key)
        while len(self._route_match_lru) > self._route_cache_maxsize:
            self._route_match_lru.popitem(last=False)
        return result

    def _is_local_request(self, method: str, url: str | httpx.URL) -> tuple[bool, SplitResult]:
        parts = urlsplit(str(url))
        path = parts.path or "/"
        if not parts.scheme and not parts.netloc:
            return self._is_local_api_path(method, path), parts

        return (
            (parts.hostname or "").lower() in _INTERNAL_HOST_ALLOWLIST
            and self._is_local_api_path(method, path),
            parts,
        )

    async def request(
        self,
        method: str,
        url: str | httpx.URL,
        **kwargs: Any,
    ) -> httpx.Response:
        is_local, parts = self._is_local_request(method, url)
        if is_local:
            local_url = parts.path or "/"
            if parts.query:
                local_url = f"{local_url}?{parts.query}"
            return await self._get_local_client().request(method, local_url, **kwargs)

        if not parts.scheme or not parts.netloc:
            raise ValueError(
                "External requests must use an absolute URL. "
                f"Received relative non-local URL: {url!s}"
            )
        return await self._get_external_client().request(method, str(url), **kwargs)

    async def aclose(self) -> None:
        if self._local_client is not None:
            await self._local_client.aclose()
            self._local_client = None
        if self._external_client is not None:
            await self._external_client.aclose()
            self._external_client = None


class InternalAwareHttpClient:
    def __init__(self, request: Request, resolver: AppHttpRouteResolver):
        self._request = request
        self._resolver = resolver

    def _build_headers(
        self,
        *,
        headers: Any = None,
        forward_auth: bool = True,
    ) -> tuple[Any, bool]:
        header_values = httpx.Headers(headers) if headers is not None else httpx.Headers()
        if forward_auth and "authorization" not in header_values:
            auth_header = self._request.headers.get("authorization")
            if auth_header:
                header_values["authorization"] = auth_header
        return header_values, bool(header_values)

    async def request(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: Any = None,
        forward_auth: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        merged_headers, has_headers = self._build_headers(headers=headers, forward_auth=forward_auth)
        if has_headers:
            kwargs["headers"] = merged_headers
        elif headers is not None:
            kwargs["headers"] = merged_headers
        return await self._resolver.request(method, url, **kwargs)

    async def get(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)


def attach_inprocess_http(app: FastAPI) -> AppHttpRouteResolver:
    resolver = getattr(app.state, _RESOLVER_STATE_KEY, None)
    if isinstance(resolver, AppHttpRouteResolver):
        return resolver
    cache_max, ext_timeout, local_timeout = _resolver_options_from_app(app)
    resolver = AppHttpRouteResolver(
        app,
        route_cache_maxsize=cache_max,
        external_timeout=ext_timeout,
        local_timeout=local_timeout,
    )
    setattr(app.state, _RESOLVER_STATE_KEY, resolver)
    return resolver


async def close_inprocess_http(app: FastAPI) -> None:
    resolver = getattr(app.state, _RESOLVER_STATE_KEY, None)
    if isinstance(resolver, AppHttpRouteResolver):
        await resolver.aclose()
        setattr(app.state, _RESOLVER_STATE_KEY, None)


def get_internal_http_client(request: Request) -> InternalAwareHttpClient:
    resolver = getattr(request.app.state, _RESOLVER_STATE_KEY, None)
    if not isinstance(resolver, AppHttpRouteResolver):
        resolver = attach_inprocess_http(request.app)
    return InternalAwareHttpClient(request=request, resolver=resolver)


__all__ = [
    "AppHttpRouteResolver",
    "InternalAwareHttpClient",
    "attach_inprocess_http",
    "close_inprocess_http",
    "get_internal_http_client",
]
