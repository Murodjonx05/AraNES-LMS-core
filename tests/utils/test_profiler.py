from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

import src.utils.profiler as profiler


def _reload_profiler_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_PROFILE_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("APP_PROFILING_ENABLED", "true")
    return importlib.reload(profiler)


def test_profile_function_always_logs_to_json_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _reload_profiler_module(tmp_path, monkeypatch)

    @module.profile_function()
    def sample() -> int:
        return 42

    assert sample() == 42

    log_path = tmp_path / "profile.log.json"
    assert log_path.exists()
    content = json.loads(log_path.read_text(encoding="utf-8"))
    assert "entries" in content
    assert "test_profiler.test_profile_function_always_logs_to_json_file.<locals>.sample" in str(content)


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
