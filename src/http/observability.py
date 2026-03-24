from __future__ import annotations

from fastapi.responses import JSONResponse

from src.auth.dependencies import peek_cached_access_token_payload
from src.runtime import RuntimeContext
from src.utils.structured_logging import get_logger

_AUDITED_PREFIXES = ("/api/v1/rbac", "/api/v1/i18n", "/api/v1/plugins")
_AUDITED_EXACT_PATHS = frozenset({"/api/v1/auth/reset"})
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CURRENT_ACTOR_STATE_KEY = "_current_actor"
_CURRENT_USER_ROLE_STATE_KEY = "_current_user_with_role"
_ACTOR_SUBJECT_WARNING_STATE_KEY = "_actor_subject_warning_emitted"


def request_logger():
    return get_logger("aranes.request")


def audit_logger():
    return get_logger("aranes.audit")


def operability_logger():
    return get_logger("aranes.operability")


def security_logger():
    return get_logger("aranes.security")


def _payload_claim(payload: object, key: str) -> object | None:
    value = getattr(payload, key, None)
    if value is not None:
        return value
    if isinstance(payload, dict):
        return payload.get(key)
    if hasattr(payload, "model_dump"):
        return payload.model_dump().get(key)
    return None


def _stable_actor_subject_from_user_id(raw_user_id: object) -> str | None:
    if isinstance(raw_user_id, int) and raw_user_id > 0:
        return f"uid:{raw_user_id}"
    if isinstance(raw_user_id, str) and raw_user_id.strip().isdigit():
        user_id = int(raw_user_id.strip())
        if user_id > 0:
            return f"uid:{user_id}"
    return None


def _stable_actor_subject_from_request_state(request) -> str | None:
    current_actor = getattr(request.state, _CURRENT_ACTOR_STATE_KEY, None)
    actor_subject = _stable_actor_subject_from_user_id(getattr(current_actor, "user_id", None))
    if actor_subject is not None:
        return actor_subject

    cached_pair = getattr(request.state, _CURRENT_USER_ROLE_STATE_KEY, None)
    if isinstance(cached_pair, tuple) and cached_pair:
        return _stable_actor_subject_from_user_id(getattr(cached_pair[0], "id", None))
    return None


def _stable_actor_subject_from_payload(payload: object) -> str | None:
    actor_subject = _stable_actor_subject_from_user_id(_payload_claim(payload, "uid"))
    if actor_subject is not None:
        return actor_subject
    username = _payload_claim(payload, "sub")
    if isinstance(username, str) and username:
        return username
    return None


def extract_actor_subject(request, runtime: RuntimeContext) -> str | None:
    del runtime
    cached = getattr(request.state, "actor_subject", None)
    if cached is not None:
        return cached
    if getattr(request.state, "actor_subject_resolved", False):
        return None
    actor_subject = _stable_actor_subject_from_request_state(request)
    if actor_subject is not None:
        request.state.actor_subject = actor_subject
        request.state.actor_subject_resolved = True
        return actor_subject

    # Reuse payload from auth dependency when present to avoid any extra work.
    payload = peek_cached_access_token_payload(request)
    if payload is not None:
        request.state.actor_subject = _stable_actor_subject_from_payload(payload)
        request.state.actor_subject_resolved = True
        return request.state.actor_subject

    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        request.state.actor_subject_resolved = True
        return None
    token = auth_header[7:].strip()
    if not token:
        request.state.actor_subject_resolved = True
        return None
    warn_actor_subject_extraction_failed(request)
    request.state.actor_subject_resolved = True
    return None


def should_audit_request(path: str, method: str) -> bool:
    if method in _READ_METHODS or method.upper() in _READ_METHODS:
        return False
    return path in _AUDITED_EXACT_PATHS or path.startswith(_AUDITED_PREFIXES)


def needs_request_observation(runtime: RuntimeContext, method: str, path: str) -> bool:
    if runtime.config.REQUEST_LOG_ENABLED:
        return True
    if not runtime.config.AUDIT_LOG_ENABLED:
        return False
    return should_audit_request(path, method)


def client_host(request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return str(request.client.host)


def apply_request_id(response: JSONResponse, request_id: str):
    response.headers["X-Request-ID"] = request_id
    return response


def warn_actor_subject_extraction_failed(request, *, error_type: str | None = None) -> None:
    if getattr(request.state, _ACTOR_SUBJECT_WARNING_STATE_KEY, False):
        return
    security_logger().warning(
        "actor subject extraction failed",
        request_id=getattr(request.state, "request_id", None),
        path=getattr(getattr(request, "url", None), "path", None),
        error_type=error_type,
    )
    setattr(request.state, _ACTOR_SUBJECT_WARNING_STATE_KEY, True)


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
    should_log_request = runtime.config.REQUEST_LOG_ENABLED
    should_log_audit = runtime.config.AUDIT_LOG_ENABLED and should_audit_request(path, method)
    if not should_log_request and not should_log_audit:
        return

    actor_subject = extract_actor_subject(request, runtime)
    if should_log_request:
        request_logger().info(
            "request",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            elapsed_ms=round(elapsed_ms, 3),
            client_host=client_host_value,
            actor=actor_subject,
        )
    if should_log_audit:
        audit_logger().info(
            "audit",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            client_host=client_host_value,
            actor=actor_subject,
        )
