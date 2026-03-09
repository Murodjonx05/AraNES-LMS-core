from __future__ import annotations

from typing import Any

from fastapi import Request
from authx.schema import RequestToken

from src.runtime import RuntimeContext, get_default_runtime

_ACCESS_TOKEN_PAYLOAD_STATE_KEY = "_access_token_payload"
_REQUEST_ACCESS_TOKEN_STATE_KEY = "_request_access_token"
_ACCESS_TOKEN_REQUIRED_DEPENDENCY_STATE_KEY = "_access_token_required_dependency"


def get_runtime_from_request(request: Request) -> RuntimeContext:
    return getattr(request.app.state, "runtime", None) or get_default_runtime()


def get_security_from_request(request: Request):
    return get_runtime_from_request(request).security


def peek_cached_access_token_payload(request: Request) -> Any:
    return getattr(request.state, _ACCESS_TOKEN_PAYLOAD_STATE_KEY, None)


def _get_access_token_required_dependency(request: Request):
    app_state = getattr(request.app, "state", None)
    if app_state is not None and (
        cached_dependency := getattr(app_state, _ACCESS_TOKEN_REQUIRED_DEPENDENCY_STATE_KEY, None)
    ) is not None:
        return cached_dependency

    security = get_security_from_request(request)
    dependency = security.token_required(
        type="access",
        verify_csrf=False,
        locations=["headers"],
    )
    if app_state is not None:
        setattr(app_state, _ACCESS_TOKEN_REQUIRED_DEPENDENCY_STATE_KEY, dependency)
    return dependency


async def get_request_access_token(request: Request) -> RequestToken:
    cached_token = getattr(request.state, _REQUEST_ACCESS_TOKEN_STATE_KEY, None)
    if cached_token is not None:
        return cached_token
    security = get_security_from_request(request)
    request_token = await security.get_access_token_from_request(request, locations=["headers"])
    setattr(request.state, _REQUEST_ACCESS_TOKEN_STATE_KEY, request_token)
    return request_token


async def require_access_token_payload(request: Request) -> Any:
    cached_payload = getattr(request.state, _ACCESS_TOKEN_PAYLOAD_STATE_KEY, None)
    if cached_payload is not None:
        return cached_payload
    dependency = _get_access_token_required_dependency(request)
    payload = await dependency(request)
    setattr(request.state, _ACCESS_TOKEN_PAYLOAD_STATE_KEY, payload)
    return payload


async def get_cached_access_token_payload(request: Request) -> Any:
    cached_payload = getattr(request.state, _ACCESS_TOKEN_PAYLOAD_STATE_KEY, None)
    if cached_payload is not None:
        return cached_payload
    return await require_access_token_payload(request)
