from __future__ import annotations

import os
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


class _TimingParts(TypedDict):
    setup: float
    call: float
    teardown: float


_TEST_TIMINGS: dict[str, _TimingParts] = {}

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


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when not in {"setup", "call", "teardown"}:
        return
    timing = _TEST_TIMINGS.setdefault(
        report.nodeid,
        {"setup": 0.0, "call": 0.0, "teardown": 0.0},
    )
    timing[report.when] += float(report.duration)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not session.config.getoption("--profile"):
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
