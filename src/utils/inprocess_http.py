from __future__ import annotations

from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from starlette.routing import Match

_LOCAL_CLIENT_BASE_URL = "http://inprocess.local"
_RESOLVER_STATE_KEY = "inprocess_http_resolver"


class AppHttpRouteResolver:
    def __init__(self, app: FastAPI):
        self._app = app
        self._api_routes = [
            route
            for route in app.routes
            if isinstance(route, APIRoute) and route.path.startswith("/api")
        ]
        self._route_match_cache: dict[tuple[str, str], bool] = {}
        self._local_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_LOCAL_CLIENT_BASE_URL,
        )
        self._external_client = httpx.AsyncClient()

    def _is_local_api_path(self, method: str, path: str) -> bool:
        if not path.startswith("/api"):
            return False
        cache_key = (method.upper(), path)
        cached = self._route_match_cache.get(cache_key)
        if cached is not None:
            return cached

        scope = {
            "type": "http",
            "method": cache_key[0],
            "path": path,
            "root_path": "",
        }
        for route in self._api_routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                self._route_match_cache[cache_key] = True
                return True
        self._route_match_cache[cache_key] = False
        return False

    def _is_local_request(self, method: str, url: str | httpx.URL) -> tuple[bool, SplitResult]:
        parts = urlsplit(str(url))
        path = parts.path or "/"
        return self._is_local_api_path(method, path), parts

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
            return await self._local_client.request(method, local_url, **kwargs)

        if not parts.scheme or not parts.netloc:
            raise ValueError(
                "External requests must use an absolute URL. "
                f"Received relative non-local URL: {url!s}"
            )
        return await self._external_client.request(method, str(url), **kwargs)

    async def aclose(self) -> None:
        await self._local_client.aclose()
        await self._external_client.aclose()


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
    resolver = AppHttpRouteResolver(app)
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
