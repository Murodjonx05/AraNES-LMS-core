from __future__ import annotations

from typing import Any

from authx.exceptions import RevokedTokenError
from fastapi import Request
from authx.schema import RequestToken

from src.runtime import RuntimeContext, get_default_runtime

_ACCESS_TOKEN_PAYLOAD_STATE_KEY = "_access_token_payload"
_REQUEST_ACCESS_TOKEN_STATE_KEY = "_request_access_token"
_ACCESS_TOKEN_REQUIRED_DEPENDENCY_STATE_KEY = "_access_token_required_dependency"
_ACCESS_TOKEN_REQUIRED_DEPENDENCY_SECURITY_STATE_KEY = "_access_token_required_dependency_security"


def get_runtime_from_request(request: Request) -> RuntimeContext:
    return getattr(request.app.state, "runtime", None) or get_default_runtime()


def get_security_from_request(request: Request):
    return get_runtime_from_request(request).security


def peek_cached_access_token_payload(request: Request) -> Any:
    return getattr(request.state, _ACCESS_TOKEN_PAYLOAD_STATE_KEY, None)


def _get_access_token_required_dependency(request: Request):
    app_state = getattr(request.app, "state", None)
    security = get_security_from_request(request)
    if app_state is not None:
        cached_dependency = getattr(app_state, _ACCESS_TOKEN_REQUIRED_DEPENDENCY_STATE_KEY, None)
        cached_security = getattr(app_state, _ACCESS_TOKEN_REQUIRED_DEPENDENCY_SECURITY_STATE_KEY, None)
        if cached_dependency is not None and cached_security is security:
            return cached_dependency

    async def dependency(inner_request: Request) -> Any:
        request_token = await get_request_access_token(inner_request)
        payload = security.verify_token(
            request_token,
            verify_type=True,
            verify_fresh=False,
            verify_csrf=False,
        )
        if await security.is_token_in_blocklist(request_token.token):
            raise RevokedTokenError("Token has been revoked")
        return payload

    if app_state is not None:
        setattr(app_state, _ACCESS_TOKEN_REQUIRED_DEPENDENCY_STATE_KEY, dependency)
        setattr(app_state, _ACCESS_TOKEN_REQUIRED_DEPENDENCY_SECURITY_STATE_KEY, security)
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
