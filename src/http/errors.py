from __future__ import annotations

from uuid import uuid4

import authx.exceptions as authx_exceptions
from fastapi import Request
from fastapi.responses import JSONResponse

from src.http.observability import (
    apply_request_id,
    operability_logger,
    warn_actor_subject_extraction_failed,
)


def resolve_request_id(request: Request) -> str:
    return (
        getattr(request.state, "request_id", None)
        or request.headers.get("x-request-id")
        or uuid4().hex
    )


def build_internal_server_error_response(request: Request, exc: Exception):
    request_id = resolve_request_id(request)
    operability_logger().exception(
        "unhandled request exception",
        request_id=request_id,
        path=request.url.path,
        error_type=exc.__class__.__name__,
    )
    return apply_request_id(
        JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "request_id": request_id},
        ),
        request_id,
    )


def build_jwt_decode_error_response(request: Request, exc: authx_exceptions.JWTDecodeError):
    """Return 401 with a safe, non-leaky message. Do not expose token or decode details to clients."""
    request_id = resolve_request_id(request)
    warn_actor_subject_extraction_failed(request, error_type=exc.__class__.__name__)
    return apply_request_id(
        JSONResponse(
            status_code=401,
            content={
                "message": "Invalid token",
                "error_type": exc.__class__.__name__,
            },
        ),
        request_id,
    )
