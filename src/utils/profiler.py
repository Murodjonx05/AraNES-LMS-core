from __future__ import annotations

import functools
import inspect
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_LOCK = threading.Lock()
_LOG_PATH: Path | None = None
_INITIALIZED = False
_STATE: dict[str, Any] | None = None

_ENV_PROFILE_LOG_DIR = "APP_PROFILE_LOG_DIR"
_ENV_PROFILE_ENABLED = "APP_PROFILING_ENABLED"
_MAX_SAMPLES_PER_KEY = 100


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "entries": {},
    }


def _ensure_initialized() -> None:
    global _INITIALIZED, _LOG_PATH, _STATE
    if _INITIALIZED:
        return

    log_dir_env = os.getenv(_ENV_PROFILE_LOG_DIR, "").strip()
    default_base_dir = Path(__file__).resolve().parents[2]
    log_dir = Path(log_dir_env) if log_dir_env else (default_base_dir / "logs")

    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = log_dir / "profile.log.json"
    if _LOG_PATH.exists():
        try:
            raw = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
                _STATE = raw
            else:
                _STATE = _default_state()
        except Exception:
            _STATE = _default_state()
    else:
        _STATE = _default_state()
        _LOG_PATH.write_text(json.dumps(_STATE, ensure_ascii=True, indent=2), encoding="utf-8")
    _INITIALIZED = True


def is_profiling_enabled() -> bool:
    raw = os.getenv(_ENV_PROFILE_ENABLED, "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def ensure_profile_log_file() -> Path:
    if not is_profiling_enabled():
        raise RuntimeError("Profiling is disabled.")
    _ensure_initialized()
    if _LOG_PATH is None:
        raise RuntimeError("Profiler log path is not initialized.")
    with _LOCK:
        _LOG_PATH.touch(exist_ok=True)
    return _LOG_PATH


def _trim_samples_keep_extremes(samples: list[dict[str, Any]]) -> None:
    while len(samples) > _MAX_SAMPLES_PER_KEY:
        min_idx = min(range(len(samples)), key=lambda i: float(samples[i]["elapsed_ms"]))
        max_idx = max(range(len(samples)), key=lambda i: float(samples[i]["elapsed_ms"]))
        protected = {min_idx, max_idx}
        remove_idx = next((i for i in range(len(samples)) if i not in protected), 0)
        samples.pop(remove_idx)


def _append_sample(*, unique_key: str, kind: str, sample: dict[str, Any]) -> None:
    if not is_profiling_enabled():
        return
    _ensure_initialized()
    if _LOG_PATH is None or _STATE is None:
        return

    with _LOCK:
        entries = _STATE.setdefault("entries", {})
        entry = entries.get(unique_key)
        if not isinstance(entry, dict):
            entry = {
                "kind": kind,
                "unique_key": unique_key,
                "count": 0,
                "fastest_ms": float(sample["elapsed_ms"]),
                "slowest_ms": float(sample["elapsed_ms"]),
                "samples": [],
            }
            entries[unique_key] = entry

        samples = entry.setdefault("samples", [])
        if not isinstance(samples, list):
            samples = []
            entry["samples"] = samples

        elapsed_ms = float(sample["elapsed_ms"])
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["fastest_ms"] = min(float(entry.get("fastest_ms", elapsed_ms)), elapsed_ms)
        entry["slowest_ms"] = max(float(entry.get("slowest_ms", elapsed_ms)), elapsed_ms)
        samples.append(sample)
        _trim_samples_keep_extremes(samples)

        _STATE["updated_at"] = datetime.now(timezone.utc).isoformat()
        _LOG_PATH.write_text(json.dumps(_STATE, ensure_ascii=True, indent=2), encoding="utf-8")


def _emit_function_profile(function_name: str, elapsed_ms: float) -> None:
    _append_sample(
        unique_key=function_name,
        kind="function",
        sample={
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round(elapsed_ms, 3),
        },
    )


def emit_request_profile(
    *,
    method: str,
    path: str,
    status_code: int,
    elapsed_ms: float,
) -> None:
    if not is_profiling_enabled():
        return
    unique_key = f"request:{method.upper()} {path}"
    _append_sample(
        unique_key=unique_key,
        kind="request",
        sample={
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "status_code": status_code,
            "elapsed_ms": round(elapsed_ms, 3),
        },
    )


def profile_function(name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def _decorator(func: Callable[P, R]) -> Callable[P, R]:
        function_name = name or f"{func.__module__}.{func.__qualname__}"
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def _async_wrapper(*args: P.args, **kwargs: P.kwargs):  # type: ignore[misc]
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)  # type: ignore[arg-type]
                finally:
                    _emit_function_profile(function_name, (time.perf_counter() - start) * 1000.0)

            return _async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync_wrapper(*args: P.args, **kwargs: P.kwargs):  # type: ignore[misc]
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                _emit_function_profile(function_name, (time.perf_counter() - start) * 1000.0)

        return _sync_wrapper  # type: ignore[return-value]

    return _decorator


__all__ = [
    "emit_request_profile",
    "ensure_profile_log_file",
    "is_profiling_enabled",
    "profile_function",
]
