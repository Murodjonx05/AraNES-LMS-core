from types import SimpleNamespace
import json

from starlette.datastructures import Headers, URL

from src.http.errors import (
    build_internal_server_error_response,
    build_jwt_decode_error_response,
    resolve_request_id,
)


class _FakeRequest:
    def __init__(self, *, request_id: str | None = None, header_request_id: str | None = None, path: str = "/boom"):
        self.state = SimpleNamespace()
        if request_id is not None:
            self.state.request_id = request_id
        self.headers = Headers({} if header_request_id is None else {"x-request-id": header_request_id})
        self.url = URL(path)


def test_resolve_request_id_prefers_request_state_over_header():
    request = _FakeRequest(request_id="state-id", header_request_id="header-id")

    assert resolve_request_id(request) == "state-id"


def test_build_internal_server_error_response_includes_request_id_in_header_and_body():
    request = _FakeRequest(request_id="req-123")

    response = build_internal_server_error_response(request, RuntimeError("boom"))

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-123"
    assert json.loads(response.body) == {
        "detail": "Internal Server Error",
        "request_id": "req-123",
    }


def test_build_jwt_decode_error_response_propagates_request_id_header():
    request = _FakeRequest(header_request_id="jwt-123")

    response = build_jwt_decode_error_response(request, ValueError("bad token"))  # type: ignore[arg-type]

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "jwt-123"
    assert json.loads(response.body)["error_type"] == "ValueError"
