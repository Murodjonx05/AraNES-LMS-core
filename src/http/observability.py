from __future__ import annotations

from fastapi.responses import JSONResponse

from src.auth.dependencies import peek_cached_access_token_payload
from src.runtime import RuntimeContext
from src.utils.structured_logging import get_logger

_AUDITED_PREFIXES = ("/api/v1/rbac", "/api/v1/i18n")
_AUDITED_EXACT_PATHS = frozenset({"/api/v1/auth/reset"})
REQUEST_LOGGER = get_logger("aranes.request")
AUDIT_LOGGER = get_logger("aranes.audit")
OPERABILITY_LOGGER = get_logger("aranes.operability")
SECURITY_LOGGER = get_logger("aranes.security")


def extract_actor_subject(request, runtime: RuntimeContext) -> str | None:
    cached = getattr(request.state, "actor_subject", None)
    if cached is not None:
        return cached
    if getattr(request.state, "actor_subject_resolved", False):
        return None

    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        request.state.actor_subject_resolved = True
        return None
    token = auth_header[7:].strip()
    if not token:
        request.state.actor_subject_resolved = True
        return None
    payload = peek_cached_access_token_payload(request)
    if payload is None:
        SECURITY_LOGGER.warning(
            "actor subject extraction failed",
            request_id=getattr(request.state, "request_id", None),
        )
        request.state.actor_subject_resolved = True
        return None
    request.state.actor_subject = getattr(payload, "sub", None)
    request.state.actor_subject_resolved = True
    return request.state.actor_subject


def should_audit_request(path: str, method: str) -> bool:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return False
    return path in _AUDITED_EXACT_PATHS or path.startswith(_AUDITED_PREFIXES)


def client_host(request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return str(request.client.host)


def apply_request_id(response: JSONResponse, request_id: str):
    response.headers["X-Request-ID"] = request_id
    return response


def record_request_observation(
    *,
    request,
    runtime: RuntimeContext,
    method: str,
    path: str,
    status_code: int,
    elapsed_ms: float,
    request_id: str,
    client_host_value: str,
) -> None:
    actor_subject = extract_actor_subject(request, runtime)
    if runtime.config.REQUEST_LOG_ENABLED:
        REQUEST_LOGGER.info(
            "request",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=round(elapsed_ms, 3),
            client_host=client_host_value,
            actor=actor_subject,
        )
    if runtime.config.AUDIT_LOG_ENABLED and should_audit_request(path, method):
        AUDIT_LOGGER.info(
            "audit",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            client_host=client_host_value,
            actor=actor_subject,
        )
