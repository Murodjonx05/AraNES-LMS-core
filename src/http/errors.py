from __future__ import annotations

from uuid import uuid4

import authx.exceptions as authx_exceptions
from fastapi import Request
from fastapi.responses import JSONResponse

from src.http.observability import (
    OPERABILITY_LOGGER,
    apply_request_id,
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
    OPERABILITY_LOGGER.exception(
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
    request_id = resolve_request_id(request)
    warn_actor_subject_extraction_failed(request, error_type=exc.__class__.__name__)
    return apply_request_id(
        JSONResponse(
            status_code=401,
            content={
                "message": str(exc) or "Invalid Token",
                "error_type": exc.__class__.__name__,
            },
        ),
        request_id,
    )
