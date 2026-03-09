from types import SimpleNamespace

import pytest
from authx.schema import RequestToken

from src.auth import dependencies


class _FakeSecurity:
    def __init__(self, name: str):
        self.name = name
        self.get_access_token_calls = 0
        self.blocklist_checks = 0
        self.verify_token_calls = 0

    async def get_access_token_from_request(self, request, *, locations: list[str]):
        del request
        self.get_access_token_calls += 1
        assert locations == ["headers"]
        return RequestToken(token=f"{self.name}-token", type="access", location="headers")

    async def is_token_in_blocklist(self, token: str) -> bool:
        self.blocklist_checks += 1
        assert token == f"{self.name}-token"
        return False

    def verify_token(self, token: RequestToken, **kwargs):
        self.verify_token_calls += 1
        assert token.token == f"{self.name}-token"
        assert kwargs["verify_type"] is True
        assert kwargs["verify_fresh"] is False
        assert kwargs["verify_csrf"] is False
        return {"security": self.name}


def _build_request(security: _FakeSecurity):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(security=security))),
        state=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_require_access_token_payload_rebuilds_dependency_when_security_changes():
    first_security = _FakeSecurity("first")
    second_security = _FakeSecurity("second")
    request = _build_request(first_security)

    first_payload = await dependencies.require_access_token_payload(request)  # type: ignore[arg-type]
    assert first_payload == {"security": "first"}
    assert first_security.get_access_token_calls == 1
    assert first_security.blocklist_checks == 1
    assert first_security.verify_token_calls == 1

    request.state = SimpleNamespace()
    request.app.state.runtime = SimpleNamespace(security=second_security)

    second_payload = await dependencies.require_access_token_payload(request)  # type: ignore[arg-type]
    assert second_payload == {"security": "second"}
    assert second_security.get_access_token_calls == 1
    assert second_security.blocklist_checks == 1
    assert second_security.verify_token_calls == 1


@pytest.mark.asyncio
async def test_get_request_access_token_is_cached_per_request():
    security = _FakeSecurity("auth")
    request = _build_request(security)

    first = await dependencies.get_request_access_token(request)  # type: ignore[arg-type]
    second = await dependencies.get_request_access_token(request)  # type: ignore[arg-type]

    assert first is second
    assert security.get_access_token_calls == 1


@pytest.mark.asyncio
async def test_require_access_token_payload_reuses_cached_request_token():
    security = _FakeSecurity("auth")
    request = _build_request(security)

    request_token = await dependencies.get_request_access_token(request)  # type: ignore[arg-type]
    payload = await dependencies.require_access_token_payload(request)  # type: ignore[arg-type]

    assert request_token.token == "auth-token"
    assert payload == {"security": "auth"}
    assert security.get_access_token_calls == 1
    assert security.blocklist_checks == 1
    assert security.verify_token_calls == 1


@pytest.mark.asyncio
async def test_get_cached_access_token_payload_is_cached_per_request():
    security = _FakeSecurity("auth")
    request = _build_request(security)

    first = await dependencies.get_cached_access_token_payload(request)  # type: ignore[arg-type]
    second = await dependencies.get_cached_access_token_payload(request)  # type: ignore[arg-type]

    assert first == {"security": "auth"}
    assert second is first
    assert security.get_access_token_calls == 1
    assert security.blocklist_checks == 1
    assert security.verify_token_calls == 1
