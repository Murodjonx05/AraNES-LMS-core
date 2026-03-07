from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

import src.utils.profiler as profiler


def _reload_profiler_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_PROFILE_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("APP_PROFILING_ENABLED", "true")
    monkeypatch.setenv("APP_FUNCTION_PROFILING_ENABLED", "true")
    return importlib.reload(profiler)


def test_profile_function_always_logs_to_json_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _reload_profiler_module(tmp_path, monkeypatch)

    @module.profile_function()
    def sample() -> int:
        return 42

    assert sample() == 42
    assert module.flush_profile_writes()

    log_path = tmp_path / "profile.log.json"
    assert log_path.exists()
    content = json.loads(log_path.read_text(encoding="utf-8"))
    assert "entries" in content
    assert "test_profiler.test_profile_function_always_logs_to_json_file.<locals>.sample" in str(content)


def test_profile_log_file_is_recreated_after_deletion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _reload_profiler_module(tmp_path, monkeypatch)
    log_path = tmp_path / "profile.log.json"

    module.emit_request_profile(method="GET", path="/api/test", status_code=200, elapsed_ms=12.3)
    assert module.flush_profile_writes()
    assert log_path.exists()

    log_path.unlink()
    assert not log_path.exists()

    module.emit_request_profile(method="GET", path="/api/test", status_code=200, elapsed_ms=45.6)
    assert module.flush_profile_writes()

    assert log_path.exists()
    content = json.loads(log_path.read_text(encoding="utf-8"))
    assert "request:GET /api/test" in content["entries"]


def test_profile_function_can_be_disabled_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_PROFILE_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("APP_PROFILING_ENABLED", "true")
    monkeypatch.setenv("APP_FUNCTION_PROFILING_ENABLED", "false")
    module = importlib.reload(profiler)

    @module.profile_function()
    def sample() -> int:
        return 7

    assert sample() == 7
    assert module.flush_profile_writes()

    log_path = tmp_path / "profile.log.json"
    content = json.loads(log_path.read_text(encoding="utf-8"))
    assert content["entries"] == {}


def test_profile_function_can_be_disabled_per_decorator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _reload_profiler_module(tmp_path, monkeypatch)

    @module.profile_function(enabled=False)
    def sample() -> int:
        return 9

    assert sample() == 9
    assert module.flush_profile_writes()

    log_path = tmp_path / "profile.log.json"
    content = json.loads(log_path.read_text(encoding="utf-8"))
    assert content["entries"] == {}


@pytest.mark.asyncio
async def test_profile_retains_100_samples_and_keeps_extremes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _reload_profiler_module(tmp_path, monkeypatch)

    key = "request:GET /api/test"

    module.emit_request_profile(method="GET", path="/api/test", status_code=200, elapsed_ms=999.0)
    module.emit_request_profile(method="GET", path="/api/test", status_code=200, elapsed_ms=0.1)

    for i in range(118):
        module.emit_request_profile(
            method="GET",
            path="/api/test",
            status_code=200,
            elapsed_ms=10.0 + float(i),
        )
    assert module.flush_profile_writes()

    log_path = tmp_path / "profile.log.json"
    content = json.loads(log_path.read_text(encoding="utf-8"))
    entry = content["entries"][key]
    samples = entry["samples"]

    assert entry["count"] == 120
    assert len(samples) == 100
    assert entry["fastest_ms"] == 0.1
    assert entry["slowest_ms"] == 999.0
    elapsed_values = [float(item["elapsed_ms"]) for item in samples]
    assert 0.1 in elapsed_values
    assert 999.0 in elapsed_values
