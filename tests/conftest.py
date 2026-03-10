from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path
import sys
from typing import TypedDict

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_root_str = str(PROJECT_ROOT)

if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Keep password hashing realistic but significantly faster in tests.
os.environ.setdefault("PBKDF2_ITERATIONS", "300")
os.environ.setdefault("APP_PROFILING_ENABLED", "false")
os.environ.setdefault("APP_FUNCTION_PROFILING_ENABLED", "false")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-pytest")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://testserver")


# ---------------------------------------------------------------------------
# Lightweight mock plugin infrastructure (replaces real subprocess + uvicorn)
# ---------------------------------------------------------------------------

DEMO_PLUGIN_OPENAPI: dict = {
    "openapi": "3.1.0",
    "info": {"title": "Demo FastAPI Service", "version": "1.0.0"},
    "paths": {
        "/health": {
            "get": {
                "summary": "Health",
                "operationId": "health",
                "responses": {"200": {"description": "Successful Response"}},
            }
        },
        "/ping": {
            "get": {
                "summary": "Ping",
                "operationId": "ping",
                "responses": {"200": {"description": "Successful Response"}},
            }
        },
        "/items": {
            "get": {
                "summary": "List Items",
                "operationId": "list_items",
                "responses": {
                    "200": {
                        "description": "Successful Response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "items": {"$ref": "#/components/schemas/Item"},
                                    "type": "array",
                                }
                            }
                        },
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Item": {
                "properties": {
                    "id": {"type": "integer", "title": "Id"},
                    "name": {"type": "string", "title": "Name"},
                },
                "type": "object",
                "required": ["id", "name"],
                "title": "Item",
            }
        }
    },
}

DEMO_PLUGIN_ROUTES: dict = {
    "/health": {"status": "ok"},
    "/ping": {"status": "ok"},
    "/items": [
        {"id": 1, "name": "alpha"},
        {"id": 2, "name": "beta"},
    ],
}


class MockPluginProcess:
    """Duck-type for ``subprocess.Popen`` used in plugin tests."""

    def __init__(self) -> None:
        self.pid = 99999
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False

    def wait(self, timeout=None):
        if self._alive:
            self._alive = False
        return 0


def _make_plugin_handler(openapi: dict, routes: dict):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/openapi.json":
                self._send(200, openapi)
            elif path in routes:
                self._send(200, routes[path])
            else:
                self._send(404, {"detail": "not found"})

        def _send(self, code: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    return _Handler


@pytest.fixture
def mock_plugin_server_factory():
    """Factory that spins up throwaway HTTP servers mimicking plugin services."""
    active: list[http.server.HTTPServer] = []

    def _start(
        port: int,
        openapi: dict = DEMO_PLUGIN_OPENAPI,
        routes: dict = DEMO_PLUGIN_ROUTES,
    ) -> tuple[http.server.HTTPServer, MockPluginProcess]:
        srv = http.server.HTTPServer(
            ("127.0.0.1", port),
            _make_plugin_handler(openapi, routes),
        )
        threading.Thread(target=srv.serve_forever, args=(0.01,), daemon=True).start()
        active.append(srv)
        return srv, MockPluginProcess()

    yield _start

    for srv in active:
        srv.shutdown()


class _TimingParts(TypedDict):
    setup: float
    call: float
    teardown: float


_TEST_TIMINGS: dict[str, _TimingParts] = {}
_PROFILE_ENABLED = False

_ANSI_RESET = "\033[0m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--profile",
        action="store_true",
        default=False,
        help="Print per-test timing profile (setup/call/teardown) at session end.",
    )
    parser.addoption(
        "--profile-top",
        action="store",
        type=int,
        default=20,
        help="Number of slowest tests to print with --profile (default: 20).",
    )


def pytest_configure(config: pytest.Config) -> None:
    global _PROFILE_ENABLED
    _PROFILE_ENABLED = bool(config.getoption("--profile"))


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not _PROFILE_ENABLED:
        return
    if report.when not in {"setup", "call", "teardown"}:
        return
    timing = _TEST_TIMINGS.setdefault(
        report.nodeid,
        {"setup": 0.0, "call": 0.0, "teardown": 0.0},
    )
    timing[report.when] += float(report.duration)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _PROFILE_ENABLED:
        return

    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is None:
        return
    use_color = bool(getattr(terminal, "isatty", False))

    def _colorize_ms(value_ms: float, text: str) -> str:
        if not use_color:
            return text
        if value_ms <= 50.0:
            return f"{_ANSI_GREEN}{text}{_ANSI_RESET}"
        if value_ms <= 250.0:
            return f"{_ANSI_YELLOW}{text}{_ANSI_RESET}"
        return f"{_ANSI_RED}{text}{_ANSI_RESET}"

    rows: list[tuple[float, str, _TimingParts]] = []
    for nodeid, timing in _TEST_TIMINGS.items():
        total = timing["setup"] + timing["call"] + timing["teardown"]
        rows.append((total, nodeid, timing))

    rows.sort(key=lambda row: row[0], reverse=True)
    top_n = max(1, int(session.config.getoption("--profile-top")))

    terminal.write_sep("=", f"Custom Test Timing Profile (top {top_n})")
    for total, nodeid, timing in rows[:top_n]:
        total_ms = total * 1000.0
        setup_ms = timing["setup"] * 1000.0
        call_ms = timing["call"] * 1000.0
        teardown_ms = timing["teardown"] * 1000.0
        total_str = _colorize_ms(total_ms, f"{total_ms:8.2f}ms")
        setup_str = _colorize_ms(setup_ms, f"{setup_ms:.2f}ms")
        call_str = _colorize_ms(call_ms, f"{call_ms:.2f}ms")
        teardown_str = _colorize_ms(teardown_ms, f"{teardown_ms:.2f}ms")
        terminal.write_line(
            f"{total_str}  {nodeid}  "
            f"(setup={setup_str} call={call_str} teardown={teardown_str})"
        )
