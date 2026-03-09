from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from src.http import observability


class _FakeRequest:
    def __init__(self, *, authorization: str | None = None):
        self.state = SimpleNamespace()
        self.headers = Headers({} if authorization is None else {"authorization": authorization})


def test_extract_actor_subject_prefers_stable_uid_from_dict_payload(monkeypatch):
    request = _FakeRequest(authorization="Bearer token")
    monkeypatch.setattr(
        observability,
        "peek_cached_access_token_payload",
        lambda current_request: {"uid": 42, "sub": "alice"},
    )

    actor_subject = observability.extract_actor_subject(request, runtime=SimpleNamespace())

    assert actor_subject == "uid:42"
    assert request.state.actor_subject == "uid:42"


def test_extract_actor_subject_prefers_cached_current_actor_over_token_subject(monkeypatch):
    request = _FakeRequest(authorization="Bearer token")
    request.state._current_actor = SimpleNamespace(user_id=7)
    monkeypatch.setattr(
        observability,
        "peek_cached_access_token_payload",
        lambda current_request: {"sub": "legacy-username"},
    )

    actor_subject = observability.extract_actor_subject(request, runtime=SimpleNamespace())

    assert actor_subject == "uid:7"
    assert request.state.actor_subject == "uid:7"


def test_record_request_observation_skips_actor_resolution_when_logs_disabled(monkeypatch):
    request = _FakeRequest(authorization="Bearer token")
    calls = {"count": 0}

    def _fake_extract_actor_subject(current_request, runtime):
        del current_request, runtime
        calls["count"] += 1
        return "uid:1"

    monkeypatch.setattr(observability, "extract_actor_subject", _fake_extract_actor_subject)

    runtime = SimpleNamespace(
        config=SimpleNamespace(REQUEST_LOG_ENABLED=False, AUDIT_LOG_ENABLED=False),
    )
    observability.record_request_observation(
        request=request,
        runtime=runtime,
        method="POST",
        path="/api/v1/auth/login",
        status_code=200,
        elapsed_ms=1.23,
        request_id="req-1",
        client_host_value="127.0.0.1",
    )

    assert calls["count"] == 0


def test_record_request_observation_skips_actor_resolution_for_non_audited_path(monkeypatch):
    request = _FakeRequest(authorization="Bearer token")
    calls = {"count": 0}

    def _fake_extract_actor_subject(current_request, runtime):
        del current_request, runtime
        calls["count"] += 1
        return "uid:1"

    monkeypatch.setattr(observability, "extract_actor_subject", _fake_extract_actor_subject)

    runtime = SimpleNamespace(
        config=SimpleNamespace(REQUEST_LOG_ENABLED=False, AUDIT_LOG_ENABLED=True),
    )
    observability.record_request_observation(
        request=request,
        runtime=runtime,
        method="POST",
        path="/api/v1/auth/login",
        status_code=200,
        elapsed_ms=1.23,
        request_id="req-1",
        client_host_value="127.0.0.1",
    )

    assert calls["count"] == 0


def test_record_request_observation_resolves_actor_for_audited_path(monkeypatch):
    request = _FakeRequest(authorization="Bearer token")
    calls = {"count": 0}

    def _fake_extract_actor_subject(current_request, runtime):
        del current_request, runtime
        calls["count"] += 1
        return "uid:1"

    monkeypatch.setattr(observability, "extract_actor_subject", _fake_extract_actor_subject)

    runtime = SimpleNamespace(
        config=SimpleNamespace(REQUEST_LOG_ENABLED=False, AUDIT_LOG_ENABLED=True),
    )
    observability.record_request_observation(
        request=request,
        runtime=runtime,
        method="POST",
        path="/api/v1/auth/reset",
        status_code=200,
        elapsed_ms=1.23,
        request_id="req-1",
        client_host_value="127.0.0.1",
    )

    assert calls["count"] == 1
